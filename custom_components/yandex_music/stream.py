"""HTTP streaming proxy for Yandex Music tracks.

Yamaha MusicCast and other UPnP/DLNA devices cannot use signed Yandex URLs
directly (they may block external HTTPS redirects or require specific headers).
This view proxies audio from Yandex through HA's local HTTP server, which
the Yamaha reaches as a plain LAN stream.

URL pattern:
  GET /api/yandex_music/stream/{entry_id}/{track_id}

No HA auth required so that Yamaha (and other DLNA renderers) can fetch audio.
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_CHUNK = 32 * 1024  # 32 KB read chunks


class YandexMusicStreamView(HomeAssistantView):
    """Proxy audio stream from Yandex Music to local devices."""

    url = "/api/yandex_music/stream/{entry_id}/{track_id}"
    name = "api:yandex_music:stream"
    requires_auth = False  # Yamaha/DLNA devices don't send HA tokens

    async def get(  # type: ignore[override]
        self,
        request: web.Request,
        entry_id: str,
        track_id: str,
    ) -> web.StreamResponse:
        """Stream a Yandex Music track."""
        hass: HomeAssistant = request.app["hass"]

        coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
        if coordinator is None:
            return web.Response(status=404, text="Integration not found")

        # track_id arrives with "_" in place of ":" (URL-safe encoding)
        track_id = track_id.replace("_", ":", 1)  # only first separator

        # Resolve the direct Yandex URL (blocking call in executor)
        try:
            yandex_url = await hass.async_add_executor_job(
                _resolve_url, coordinator.client, track_id
            )
        except Exception as err:
            _LOGGER.error("Cannot resolve Yandex URL for %s: %s", track_id, err)
            return web.Response(status=502, text="Cannot resolve track URL")

        if not yandex_url:
            return web.Response(status=404, text="Track URL not found")

        _LOGGER.debug("Proxying %s → %s", track_id, yandex_url[:80])

        # Forward Range header if the client (Yamaha) is seeking
        headers = {}
        if "Range" in request.headers:
            headers["Range"] = request.headers["Range"]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    yandex_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=None, connect=10),
                ) as upstream:
                    response_headers = {
                        "Content-Type": upstream.headers.get("Content-Type", "audio/mpeg"),
                        "Accept-Ranges": "bytes",
                        "Cache-Control": "no-cache",
                    }
                    if "Content-Length" in upstream.headers:
                        response_headers["Content-Length"] = upstream.headers["Content-Length"]
                    if "Content-Range" in upstream.headers:
                        response_headers["Content-Range"] = upstream.headers["Content-Range"]

                    resp = web.StreamResponse(
                        status=upstream.status,
                        headers=response_headers,
                    )
                    await resp.prepare(request)

                    async for chunk in upstream.content.iter_chunked(_CHUNK):
                        await resp.write(chunk)

                    await resp.write_eof()
                    return resp

        except asyncio.CancelledError:
            # Client disconnected — normal
            raise
        except Exception as err:
            _LOGGER.error("Streaming error for %s: %s", track_id, err)
            return web.Response(status=502, text="Stream error")


def _resolve_url(client, track_id: str) -> str | None:
    """Synchronously resolve a direct MP3 URL for the given track_id."""
    tracks = client.tracks([track_id])
    if not tracks:
        return None
    track = tracks[0]
    infos = track.get_download_info(get_direct_links=True)
    if not infos:
        return None
    mp3 = [i for i in infos if getattr(i, "codec", "") == "mp3"]
    best = sorted(mp3 or infos, key=lambda i: getattr(i, "bitrate_in_kbps", 0), reverse=True)
    return best[0].direct_link if best else None
