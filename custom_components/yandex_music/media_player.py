"""Yandex Music MediaPlayer entity."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.network import get_url
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEFAULT_STATION,
    CONF_TARGET_PLAYER,
    DEFAULT_STATION,
    DOMAIN,
    MEDIA_TYPE_LIKED,
    MEDIA_TYPE_PLAYLIST,
    MEDIA_TYPE_STATION,
    MEDIA_TYPE_TRACK,
    PLACEHOLDER_IMAGE,
    PREDEFINED_STATIONS,
)
from . import YandexMusicCoordinator

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.SHUFFLE_SET
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Yandex Music media player."""
    coordinator: YandexMusicCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([YandexMusicMediaPlayer(hass, entry, coordinator)], True)


class YandexMusicMediaPlayer(MediaPlayerEntity):
    """Yandex Music virtual media player that manages a track queue."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = SUPPORTED_FEATURES
    _attr_media_content_type = MediaType.MUSIC

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: YandexMusicCoordinator,
    ) -> None:
        """Initialize the media player."""
        self.hass = hass
        self._entry = entry
        self._coordinator = coordinator

        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Yandex",
            "model": "Yandex Music",
        }

        # Playback state
        self._state = MediaPlayerState.IDLE
        self._queue: list[dict] = []
        self._queue_pos: int = 0
        self._shuffle: bool = False

        # Position tracking (for NaN:NaN fix)
        self._play_started_at: datetime | None = None

        # Current station for refilling the queue
        self._current_station_id: str | None = None
        self._current_station_mood: str | None = None

        # Target media player entity_id
        self._unsub_target_listener = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> MediaPlayerState:
        return self._state

    @property
    def shuffle(self) -> bool:
        return self._shuffle

    @property
    def _current_track(self) -> dict | None:
        if self._queue and 0 <= self._queue_pos < len(self._queue):
            return self._queue[self._queue_pos]
        return None

    @property
    def media_title(self) -> str | None:
        t = self._current_track
        return t["title"] if t else None

    @property
    def media_artist(self) -> str | None:
        t = self._current_track
        return t.get("artist") if t else None

    @property
    def media_album_name(self) -> str | None:
        t = self._current_track
        return t.get("album") if t else None

    @property
    def media_image_url(self) -> str | None:
        t = self._current_track
        if t:
            return t.get("cover_uri") or PLACEHOLDER_IMAGE
        return None

    @property
    def media_duration(self) -> float | None:
        t = self._current_track
        if t and t.get("duration_ms"):
            return float(t["duration_ms"]) / 1000.0
        return None

    @property
    def media_position(self) -> float | None:
        if self._state == MediaPlayerState.PLAYING and self._play_started_at:
            elapsed = (dt_util.utcnow() - self._play_started_at).total_seconds()
            duration = self.media_duration
            if duration:
                return min(elapsed, duration)
            return elapsed
        return None

    @property
    def media_position_updated_at(self) -> datetime | None:
        return self._play_started_at

    @property
    def _target_player(self) -> str | None:
        return self._entry.options.get(CONF_TARGET_PLAYER) or None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Subscribe to target player state changes."""
        self._subscribe_target_listener()

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from state changes."""
        if self._unsub_target_listener:
            self._unsub_target_listener()

    def _subscribe_target_listener(self) -> None:
        """Set up listener for target media player state changes."""
        if self._unsub_target_listener:
            self._unsub_target_listener()
            self._unsub_target_listener = None

        target = self._target_player
        if not target:
            return

        @callback
        def _on_target_state_change(event):
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            if new_state.state == "idle" and self._state == MediaPlayerState.PLAYING:
                _LOGGER.debug("Target player went idle, advancing queue")
                self.hass.async_create_task(self._advance_queue())

        self._unsub_target_listener = self.hass.bus.async_listen(
            "state_changed",
            _on_target_state_change,
            event_filter=lambda e: e.data.get("entity_id") == target,
        )

    # ------------------------------------------------------------------
    # Playback controls
    # ------------------------------------------------------------------

    async def async_media_play(self) -> None:
        """Resume playback."""
        if self._state == MediaPlayerState.PAUSED and self._current_track:
            await self._send_to_target("media_player", "media_play", {})
            self._state = MediaPlayerState.PLAYING
            self.async_write_ha_state()
        elif self._state == MediaPlayerState.IDLE:
            # Play default station
            default = self._entry.options.get(CONF_DEFAULT_STATION, DEFAULT_STATION)
            await self.async_play_media(
                media_type=MEDIA_TYPE_STATION,
                media_id=f"station:{default}",
            )

    async def async_media_pause(self) -> None:
        """Pause playback."""
        await self._send_to_target("media_player", "media_pause", {})
        self._state = MediaPlayerState.PAUSED
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        """Stop playback."""
        await self._send_to_target("media_player", "media_stop", {})
        self._state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        """Skip to next track."""
        await self._advance_queue()

    async def async_media_previous_track(self) -> None:
        """Go to previous track."""
        if self._queue_pos > 0:
            self._queue_pos -= 1
            await self._play_current_track()
        self.async_write_ha_state()

    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Enable/disable shuffle."""
        self._shuffle = shuffle
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # play_media — entry point for automations and browser
    # ------------------------------------------------------------------

    async def async_play_media(
        self,
        media_type: str,
        media_id: str,
        **kwargs: Any,
    ) -> None:
        """Handle play_media calls.

        media_id formats:
          station:<station_key>           — predefined station (e.g. "station:calm")
          station_id:<raw_station_id>     — raw station id (e.g. "station_id:user:onyourwave")
          playlist:<uid>:<kind>           — user playlist
          liked:tracks                    — liked tracks
          track:<track_id>                — single track
        """
        _LOGGER.debug("play_media called: type=%s id=%s", media_type, media_id)

        if media_id.startswith("station:"):
            station_key = media_id[len("station:"):]
            station_cfg = PREDEFINED_STATIONS.get(station_key)
            if station_cfg:
                await self._load_station(
                    station_cfg["station_id"],
                    station_cfg["mood_energy"],
                )
            else:
                _LOGGER.warning("Unknown station key: %s", station_key)
            return

        if media_id.startswith("station_id:"):
            raw_id = media_id[len("station_id:"):]
            await self._load_station(raw_id, None)
            return

        if media_id.startswith("playlist:"):
            parts = media_id[len("playlist:"):].split(":")
            if len(parts) == 2:
                uid, kind = int(parts[0]), int(parts[1])
                await self._load_playlist(uid, kind)
            return

        if media_id.startswith("liked:"):
            await self._load_liked_tracks()
            return

        if media_id.startswith("track:"):
            track_id = media_id[len("track:"):]
            await self._play_single_track(track_id)
            return

        _LOGGER.warning("Unrecognised media_id: %s", media_id)

    # ------------------------------------------------------------------
    # Loading sources
    # ------------------------------------------------------------------

    async def _load_station(self, station_id: str, mood_energy: str | None) -> None:
        """Load tracks from a rotor station and start playback."""
        self._current_station_id = station_id
        self._current_station_mood = mood_energy
        try:
            tracks = await self.hass.async_add_executor_job(
                self._fetch_station_tracks, station_id, mood_energy
            )
        except Exception as err:
            _LOGGER.error("Failed to load station %s: %s", station_id, err)
            return

        if not tracks:
            _LOGGER.warning("No tracks returned for station %s", station_id)
            return

        self._queue = tracks
        self._queue_pos = 0
        if self._shuffle:
            import random
            random.shuffle(self._queue)
        await self._play_current_track()

    def _fetch_station_tracks(self, station_id: str, mood_energy: str | None) -> list[dict]:
        """Synchronously fetch tracks from a rotor station."""
        from yandex_music import StationSettings2

        settings = None
        if mood_energy:
            settings = StationSettings2(mood_energy=mood_energy, diversity="default")

        result = self._coordinator.client.rotor_station_tracks(
            station=station_id,
            settings2=settings,
            queue=None,
        )

        if result is None:
            return []

        tracks = []
        for item in result.sequence:
            track = item.track
            if track is None:
                continue
            tracks.append(_track_to_dict(track))
        return tracks

    async def _load_playlist(self, uid: int, kind: int) -> None:
        """Load tracks from a user playlist."""
        try:
            tracks = await self.hass.async_add_executor_job(
                self._fetch_playlist_tracks, uid, kind
            )
        except Exception as err:
            _LOGGER.error("Failed to load playlist %s:%s: %s", uid, kind, err)
            return

        if not tracks:
            return

        self._current_station_id = None
        self._queue = tracks
        self._queue_pos = 0
        if self._shuffle:
            import random
            random.shuffle(self._queue)
        await self._play_current_track()

    def _fetch_playlist_tracks(self, uid: int, kind: int) -> list[dict]:
        """Synchronously fetch playlist tracks."""
        playlists = self._coordinator.client.users_playlists(kind=kind, user_id=uid)
        if not playlists:
            return []
        playlist = playlists if not isinstance(playlists, list) else playlists[0]
        track_shorts = playlist.fetch_tracks()
        tracks = []
        for ts in track_shorts:
            track = ts.fetch_track()
            if track:
                tracks.append(_track_to_dict(track))
        return tracks

    async def _load_liked_tracks(self) -> None:
        """Load liked tracks."""
        try:
            tracks = await self.hass.async_add_executor_job(self._fetch_liked_tracks)
        except Exception as err:
            _LOGGER.error("Failed to load liked tracks: %s", err)
            return

        if not tracks:
            return

        self._current_station_id = None
        self._queue = tracks
        self._queue_pos = 0
        if self._shuffle:
            import random
            random.shuffle(self._queue)
        await self._play_current_track()

    def _fetch_liked_tracks(self) -> list[dict]:
        """Synchronously fetch liked tracks."""
        liked = self._coordinator.client.users_likes_tracks()
        if not liked:
            return []
        track_shorts = liked.fetch_tracks()
        return [_track_to_dict(t) for t in track_shorts if t]

    async def _play_single_track(self, track_id: str) -> None:
        """Play a single track by id."""
        self._queue = []
        self._queue_pos = 0
        try:
            track_info = await self.hass.async_add_executor_job(
                self._fetch_track_info, track_id
            )
        except Exception as err:
            _LOGGER.error("Failed to fetch track %s: %s", track_id, err)
            return

        if track_info:
            self._queue = [track_info]
            await self._play_current_track()

    def _fetch_track_info(self, track_id: str) -> dict | None:
        """Synchronously fetch a single track."""
        tracks = self._coordinator.client.tracks([track_id])
        if tracks:
            return _track_to_dict(tracks[0])
        return None

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    async def _advance_queue(self) -> None:
        """Move to the next track, refilling from station if needed."""
        if not self._queue:
            self._state = MediaPlayerState.IDLE
            self.async_write_ha_state()
            return

        self._queue_pos += 1

        # Refill from station when near the end
        if (
            self._current_station_id
            and self._queue_pos >= len(self._queue) - 3
        ):
            asyncio.ensure_future(self._refill_station_queue())

        if self._queue_pos >= len(self._queue):
            if self._current_station_id:
                # Wait briefly for refill
                await asyncio.sleep(1)
            if self._queue_pos >= len(self._queue):
                self._state = MediaPlayerState.IDLE
                self.async_write_ha_state()
                return

        await self._play_current_track()

    async def _refill_station_queue(self) -> None:
        """Append more tracks from the current station to the queue."""
        try:
            new_tracks = await self.hass.async_add_executor_job(
                self._fetch_station_tracks,
                self._current_station_id,
                self._current_station_mood,
            )
            if new_tracks:
                self._queue.extend(new_tracks)
                _LOGGER.debug("Refilled station queue, total tracks: %d", len(self._queue))
        except Exception as err:
            _LOGGER.error("Failed to refill queue: %s", err)

    async def _play_current_track(self) -> None:
        """Build a local proxy URL and send it to the target media player."""
        track = self._current_track
        if not track:
            self._state = MediaPlayerState.IDLE
            self.async_write_ha_state()
            return

        # Build a local HA proxy URL so that Yamaha/DLNA devices can fetch
        # audio from our HA server rather than directly from Yandex.
        stream_url = self._build_stream_url(track["id"])
        _LOGGER.debug(
            "Playing track '%s — %s' via %s",
            track.get("artist"),
            track.get("title"),
            stream_url,
        )

        target = self._target_player
        if target:
            await self.hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": target,
                    "media_content_id": stream_url,
                    "media_content_type": "music",
                },
                blocking=False,
            )
        else:
            _LOGGER.warning(
                "No target_player configured. Set one in integration options. "
                "Stream URL: %s",
                stream_url,
            )

        self._play_started_at = dt_util.utcnow()
        self._state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    def _build_stream_url(self, track_id: str) -> str:
        """Build a local HTTP proxy URL for the given track_id.

        The URL points to our YandexMusicStreamView which resolves the
        actual Yandex direct link and proxies the audio bytes.
        """
        try:
            base = get_url(self.hass, allow_internal=True, allow_ip=True)
        except Exception:
            base = "http://homeassistant.local:8123"

        # track_id may contain ":" (e.g. "12345:678") — encode it
        safe_id = track_id.replace(":", "_")
        return f"{base}/api/yandex_music/stream/{self._entry.entry_id}/{safe_id}"

    async def _send_to_target(self, domain: str, service: str, data: dict) -> None:
        """Call a service on the target media player."""
        target = self._target_player
        if not target:
            return
        await self.hass.services.async_call(
            domain,
            service,
            {"entity_id": target, **data},
            blocking=False,
        )

    # ------------------------------------------------------------------
    # Media browser
    # ------------------------------------------------------------------

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Return browsable media tree."""

        # Root level
        if media_content_id is None or media_content_id == "":
            return self._browse_root()

        if media_content_id == "stations":
            return self._browse_stations()

        if media_content_id == "playlists":
            return await self._browse_playlists()

        if media_content_id == "liked":
            return await self._browse_liked()

        _LOGGER.warning("Unknown browse media_content_id: %s", media_content_id)
        return self._browse_root()

    def _browse_root(self) -> BrowseMedia:
        children = [
            BrowseMedia(
                title="Станции и настроение",
                media_class="directory",
                media_content_type="directory",
                media_content_id="stations",
                can_play=False,
                can_expand=True,
                thumbnail=None,
            ),
            BrowseMedia(
                title="Мои плейлисты",
                media_class="directory",
                media_content_type="directory",
                media_content_id="playlists",
                can_play=False,
                can_expand=True,
                thumbnail=None,
            ),
            BrowseMedia(
                title="Мне нравится",
                media_class="playlist",
                media_content_type=MEDIA_TYPE_LIKED,
                media_content_id="liked:tracks",
                can_play=True,
                can_expand=True,
                thumbnail=None,
            ),
        ]
        return BrowseMedia(
            title="Yandex Music",
            media_class="directory",
            media_content_type="directory",
            media_content_id="",
            can_play=False,
            can_expand=True,
            children=children,
        )

    def _browse_stations(self) -> BrowseMedia:
        children = [
            BrowseMedia(
                title=cfg["name"],
                media_class="music",
                media_content_type=MEDIA_TYPE_STATION,
                media_content_id=f"station:{key}",
                can_play=True,
                can_expand=False,
                thumbnail=None,
            )
            for key, cfg in PREDEFINED_STATIONS.items()
        ]
        return BrowseMedia(
            title="Станции и настроение",
            media_class="directory",
            media_content_type="directory",
            media_content_id="stations",
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def _browse_playlists(self) -> BrowseMedia:
        data = self._coordinator.data or {}
        playlists = data.get("playlists", [])
        children = [
            BrowseMedia(
                title=p["title"],
                media_class="playlist",
                media_content_type=MEDIA_TYPE_PLAYLIST,
                media_content_id=f"playlist:{p['uid']}:{p['kind']}",
                can_play=True,
                can_expand=False,
                thumbnail=p.get("cover_uri"),
            )
            for p in playlists
        ]
        return BrowseMedia(
            title="Мои плейлисты",
            media_class="directory",
            media_content_type="directory",
            media_content_id="playlists",
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def _browse_liked(self) -> BrowseMedia:
        try:
            tracks = await self.hass.async_add_executor_job(self._fetch_liked_tracks)
        except Exception as err:
            _LOGGER.error("Cannot browse liked tracks: %s", err)
            tracks = []

        children = [
            BrowseMedia(
                title=f"{t.get('artist', '')} — {t.get('title', '')}",
                media_class="music",
                media_content_type=MEDIA_TYPE_TRACK,
                media_content_id=f"track:{t['id']}",
                can_play=True,
                can_expand=False,
                thumbnail=t.get("cover_uri"),
            )
            for t in tracks
        ]
        return BrowseMedia(
            title="Мне нравится",
            media_class="playlist",
            media_content_type=MEDIA_TYPE_LIKED,
            media_content_id="liked:tracks",
            can_play=True,
            can_expand=True,
            children=children,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _track_to_dict(track) -> dict:
    """Convert a yandex_music Track object to a plain dict."""
    artists = getattr(track, "artists", []) or []
    artist_name = ", ".join(
        a.name for a in artists if getattr(a, "name", None)
    )

    albums = getattr(track, "albums", []) or []
    album_name = albums[0].title if albums and getattr(albums[0], "title", None) else None

    cover = None
    if albums and getattr(albums[0], "cover_uri", None):
        uri = albums[0].cover_uri
        if uri.startswith("//"):
            uri = "https:" + uri
        cover = uri.replace("%%", "200x200")

    duration_ms = getattr(track, "duration_ms", None)
    track_id = str(track.id)
    if albums and getattr(albums[0], "id", None):
        track_id = f"{track.id}:{albums[0].id}"

    return {
        "id": track_id,
        "title": getattr(track, "title", "Unknown"),
        "artist": artist_name or None,
        "album": album_name,
        "cover_uri": cover,
        "duration_ms": duration_ms,
    }
