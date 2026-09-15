from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.endpoints import router
from src.config import HEADERS

import httpx
import os
from urllib.parse import quote, urljoin


app = FastAPI(title="Kuhi API", version="2.0")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


if os.path.exists("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")


app.include_router(router, prefix="/anime")


def _norm_url(url: str) -> str | None:
    url = (url or "").strip()

    if url.startswith("//"):
        return "https:" + url

    if url.startswith("http://") or url.startswith("https://"):
        return url

    return None


@app.get("/proxy_m3u8")
async def proxy_m3u8(url: str, referer: str):
    url = _norm_url(url)

    if not url:
        return Response(
            content='{"detail":"bad proxy url"}',
            status_code=400,
            media_type="application/json",
        )

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
        ) as client:

            headers = HEADERS.copy()
            headers["Referer"] = referer

            response = await client.get(url, headers=headers)

            content_type = response.headers.get(
                "content-type",
                "application/vnd.apple.mpegurl",
            )

            text = response.text.strip()

            if text.startswith("Found. Redirecting to "):
                redirected_url = text[
                    len("Found. Redirecting to "):
                ].strip()

                redirected_url = _norm_url(redirected_url)

                if redirected_url:
                    response = await client.get(
                        redirected_url,
                        headers=headers,
                        follow_redirects=True,
                    )

                    content_type = response.headers.get(
                        "content-type",
                        "application/octet-stream",
                    )

            if (
                "mpegurl" not in content_type.lower()
                and "m3u8" not in content_type.lower()
            ):
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    media_type=content_type.split(";")[0],
                    headers={
                        "Accept-Ranges": "bytes",
                        "Cache-Control": "no-cache",
                        "Access-Control-Allow-Origin": "*",
                    },
                )

            playlist = response.text
            rewritten_lines = []

            for line in playlist.splitlines():
                stripped = line.strip()

                if not stripped:
                    rewritten_lines.append(line)
                    continue

                if stripped.startswith("#"):
                    if 'URI="' in line:
                        try:
                            start = line.index('URI="') + 5
                            end = line.index('"', start)
                            original_uri = line[start:end]
                            absolute_uri = urljoin(url, original_uri)

                            proxied_uri = (
                                "/proxy_m3u8?url="
                                + quote(absolute_uri, safe="")
                                + "&referer="
                                + quote(referer, safe="")
                            )

                            line = (
                                line[:start]
                                + proxied_uri
                                + line[end:]
                            )
                        except Exception:
                            pass

                    rewritten_lines.append(line)
                    continue

                absolute_url = urljoin(url, stripped)
                lower_url = absolute_url.lower()

                if ".m3u8" in lower_url or ".m3u" in lower_url:
                    proxied = (
                        "/proxy_m3u8?url="
                        + quote(absolute_url, safe="")
                        + "&referer="
                        + quote(referer, safe="")
                    )
                else:
                    proxied = (
                        "/proxy_segment?url="
                        + quote(absolute_url, safe="")
                        + "&referer="
                        + quote(referer, safe="")
                    )

                rewritten_lines.append(proxied)

            return Response(
                content="\n".join(rewritten_lines),
                media_type="application/vnd.apple.mpegurl",
                headers={
                    "Cache-Control": "no-cache",
                    "Access-Control-Allow-Origin": "*",
                },
            )

    except Exception as e:
        return Response(
            content=(
                '{"detail":"proxy m3u8 error: '
                + str(e).replace('"', "'")
                + '"}'
            ),
            status_code=502,
            media_type="application/json",
        )


@app.get("/proxy_segment")
async def proxy_segment(url: str, referer: str):
    url = _norm_url(url)

    if not url:
        return Response(
            content='{"detail":"bad proxy url"}',
            status_code=400,
            media_type="application/json",
        )

    try:
        async with httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=False,
        ) as client:

            headers = HEADERS.copy()
            headers["Referer"] = referer

            response = await client.get(
                url,
                headers=headers,
            )

            content_type = response.headers.get(
                "content-type",
                "application/octet-stream",
            )

            if response.status_code in (
                301,
                302,
                303,
                307,
                308,
            ):
                location = response.headers.get("location")

                if location:
                    redirected_url = _norm_url(location)

                    if redirected_url:
                        response = await client.get(
                            redirected_url,
                            headers=headers,
                            follow_redirects=True,
                        )

                        content_type = response.headers.get(
                            "content-type",
                            "application/octet-stream",
                        )

            else:
                if (
                    "text" in content_type.lower()
                    or "html" in content_type.lower()
                    or content_type == "application/octet-stream"
                ):
                    try:
                        text = response.content.decode(
                            "utf-8",
                            errors="ignore",
                        ).strip()

                        prefix = "Found. Redirecting to "

                        if text.startswith(prefix):
                            redirected_url = text[
                                len(prefix):
                            ].strip()

                            redirected_url = _norm_url(
                                redirected_url
                            )

                            if redirected_url:
                                response = await client.get(
                                    redirected_url,
                                    headers=headers,
                                    follow_redirects=True,
                                )

                                content_type = response.headers.get(
                                    "content-type",
                                    "application/octet-stream",
                                )
                    except Exception:
                        pass

            media_type = content_type.split(";")[0].strip()

            if not media_type:
                media_type = "application/octet-stream"

            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type=media_type,
                headers={
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "no-cache",
                    "Access-Control-Allow-Origin": "*",
                },
            )

    except Exception as e:
        return Response(
            content=(
                '{"detail":"proxy error: '
                + str(e).replace('"', "'")
                + '"}'
            ),
            status_code=502,
            media_type="application/json",
        )


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(
        content="""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kuhi API</title>
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<style>
* { box-sizing: border-box; }
body {
    margin: 0;
    padding: 0;
    background: #0b0b0f;
    color: #fff;
    font-family: Arial, Helvetica, sans-serif;
}
.container {
    max-width: 1100px;
    margin: auto;
    padding: 30px 20px;
}
.hero {
    text-align: center;
    padding: 50px 20px 30px;
}
.hero h1 {
    font-size: 42px;
    margin-bottom: 10px;
}
.hero p {
    color: #aaa;
    font-size: 16px;
}
.card {
    background: #15151c;
    border-radius: 14px;
    padding: 20px;
    margin-top: 25px;
    border: 1px solid #252530;
}
.card h2 { margin-top: 0; }
input, select, button {
    width: 100%;
    padding: 13px;
    margin-top: 10px;
    border-radius: 8px;
    border: 1px solid #333;
    background: #0f0f14;
    color: #fff;
}
button {
    cursor: pointer;
    background: #252530;
}
button:hover { background: #33333f; }
video {
    width: 100%;
    max-height: 650px;
    margin-top: 20px;
    background: #000;
    border-radius: 10px;
}
pre {
    white-space: pre-wrap;
    word-break: break-word;
    background: #09090d;
    padding: 15px;
    border-radius: 8px;
    overflow-x: auto;
}
.status {
    margin-top: 12px;
    color: #aaa;
}
</style>
</head>

<body>
<div class="container">

<div class="hero">
<h1>Kuhi API</h1>
<p>Anime metadata, episodes, streaming extraction and proxy API.</p>
</div>

<div class="card">
<h2>Anime Stream Test</h2>

<input id="animeId" type="number" value="21" placeholder="AniList ID">
<input id="episode" type="number" value="1" min="1" placeholder="Episode">

<select id="type">
<option value="sub">SUB</option>
<option value="dub">DUB</option>
</select>

<button onclick="loadStream()">Load Stream</button>

<div id="status" class="status">Ready.</div>

<video id="video" controls playsinline></video>

<pre id="output"></pre>
</div>

</div>

<script>
let hls = null;

function setStatus(text) {
    document.getElementById("status").textContent = text;
}

async function loadStream() {
    const animeId = document.getElementById("animeId").value;
    const episode = document.getElementById("episode").value;
    const type = document.getElementById("type").value;

    const video = document.getElementById("video");
    const output = document.getElementById("output");

    setStatus("Extracting stream...");
    output.textContent = "";

    if (hls) {
        hls.destroy();
        hls = null;
    }

    video.removeAttribute("src");
    video.load();

    try {
        const response = await fetch(
            "/anime/extract/"
            + animeId
            + "?e="
            + episode
            + "&type="
            + type
        );

        const data = await response.json();

        output.textContent = JSON.stringify(data, null, 2);

        if (!data.streams || data.streams.length === 0) {
            setStatus("No streams found.");
            return;
        }

        let stream = data.streams.find(s => s.isActive);

        if (!stream) {
            stream = data.streams.find(s => s.type === "hls");
        }

        if (!stream) {
            stream = data.streams.find(s => s.type === "mp4");
        }

        if (!stream) {
            stream = data.streams[0];
        }

        if (!stream.url) {
            setStatus("Stream URL missing.");
            return;
        }

        const streamUrl = stream.url;
        const referer = stream.referer || "https://www.animegg.org/";

        if (
            stream.type === "hls"
            || streamUrl.toLowerCase().includes(".m3u8")
        ) {
            const proxyUrl =
                "/proxy_m3u8?url="
                + encodeURIComponent(streamUrl)
                + "&referer="
                + encodeURIComponent(referer);

            if (Hls.isSupported()) {
                hls = new Hls();

                hls.loadSource(proxyUrl);
                hls.attachMedia(video);

                hls.on(
                    Hls.Events.MANIFEST_PARSED,
                    function() {
                        setStatus("HLS stream ready.");
                    }
                );

                hls.on(
                    Hls.Events.ERROR,
                    function(event, data) {
                        console.error("HLS error:", data);
                        setStatus("HLS playback error.");
                    }
                );
            } else if (
                video.canPlayType(
                    "application/vnd.apple.mpegurl"
                )
            ) {
                video.src = proxyUrl;
                setStatus("HLS stream ready.");
            }

            return;
        }

        if (
            stream.type === "mp4"
            || streamUrl.toLowerCase().includes(".mp4")
        ) {
            const proxyUrl =
                "/proxy_segment?url="
                + encodeURIComponent(streamUrl)
                + "&referer="
                + encodeURIComponent(referer);

            video.src = proxyUrl;
            video.load();

            setStatus("MP4 stream ready.");
            return;
        }

        if (stream.type === "embed") {
            setStatus(
                "Embed stream detected. Direct video playback is not available."
            );
            return;
        }

        setStatus(
            "Unsupported stream type: " + stream.type
        );

    } catch (error) {
        console.error(error);
        setStatus("Failed to load stream.");
    }
}
</script>

</body>
</html>
"""
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "Kuhi API",
    }
