"""Yandex Music MediaPlayer entity."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.network import get_url
from homeassistant.util import dt as dt_util

from . import YandexMusicCoordinator
from .const import (
    CONF_DEFAULT_SOURCE,
    CONF_DEFAULT_STATION,
    CONF_TARGET_PLAYER,
    DATA_STREAM_MANAGER,
    DEFAULT_STATION,
    DOMAIN,
    MEDIA_TYPE_LIKED,
    MEDIA_TYPE_PLAYLIST,
    MEDIA_TYPE_STATION,
    MEDIA_TYPE_TRACK,
    PLACEHOLDER_IMAGE,
    PREDEFINED_STATIONS,
)
from .source_catalog import media_type_for_source, normalize_default_source
from .stream_manager import YandexMusicStreamManager

_LOGGER = logging.getLogger(__name__)

# Yamaha MusicCast briefly transitions through "idle" right after receiving a
# play command (source switch, buffering).  Ignore idle events that arrive
# within this window so we don't cycle through the whole queue instantly.
_PLAY_COOLDOWN_SEC = 8
_IDLE_DEBOUNCE_SEC = 1
_TRACK_END_TOLERANCE_SEC = 5

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Yandex Music media player."""
    coordinator: YandexMusicCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([YandexMusicMediaPlayer(hass, entry, coordinator)], False)


class YandexMusicMediaPlayer(MediaPlayerEntity):
    """Yandex Music virtual media player that manages a track queue."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False   # updates driven by coordinator listener, not HA polling
    _attr_available = True      # always available while config entry is loaded
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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Yandex",
            model="Yandex Music",
        )

        # Playback state
        self._state = MediaPlayerState.IDLE
        self._queue: list[dict] = []
        self._queue_pos: int = 0
        self._shuffle: bool = False

        # Position / cooldown tracking
        self._play_started_at: datetime | None = None
        # Timestamp of the last _play_current_track call.
        # We ignore "idle" events from the target player that arrive within
        # _PLAY_COOLDOWN_SEC seconds of this — Yamaha briefly flashes "idle"
        # right after receiving a play command before it starts buffering.
        self._last_play_command_at: datetime | None = None
        self._control_generation = 0

        # Current station for refilling the queue
        self._current_station_id: str | None = None
        self._current_station_mood: str | None = None

        # Target media player entity_id
        self._unsub_target_listener = None
        self._idle_check_task: asyncio.Task | None = None

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
        """Subscribe to coordinator updates and target player state changes."""
        await super().async_added_to_hass()
        # Listen to coordinator refreshes so the media browser stays current
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self._subscribe_target_listener()

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from state changes."""
        if self._unsub_target_listener:
            self._unsub_target_listener()
        self._new_control_generation()
        self._stream_manager.stop(self._entry.entry_id)
        await super().async_will_remove_from_hass()

    def _subscribe_target_listener(self) -> None:
        """Set up listener for target media player state changes."""
        if self._unsub_target_listener:
            self._unsub_target_listener()
            self._unsub_target_listener = None

        target = self._target_player
        if not target:
            return

        @callback
        def _on_target_state_change(event) -> None:
            # Filter by entity_id manually — avoids event_filter compatibility issues
            if event.data.get("entity_id") != target:
                return
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            if new_state.state != "idle":
                self._cancel_idle_check()
            if self._state != MediaPlayerState.PLAYING:
                return
            if new_state.state in {"off", "unavailable", "unknown"}:
                _LOGGER.debug(
                    "Target player %s became %s; stopping proxy stream",
                    target,
                    new_state.state,
                )
                self._stop_local(
                    MediaPlayerState.OFF
                    if new_state.state == "off"
                    else MediaPlayerState.IDLE
                )
                return
            if new_state.state != "idle":
                return
            # Cooldown: Yamaha briefly hits "idle" during source switch / buffering.
            # Skip idle events that arrive too soon after we sent the play command.
            if self._last_play_command_at is not None:
                elapsed = (
                    dt_util.utcnow() - self._last_play_command_at
                ).total_seconds()
                if elapsed < _PLAY_COOLDOWN_SEC:
                    delay = _PLAY_COOLDOWN_SEC - elapsed + _IDLE_DEBOUNCE_SEC
                    _LOGGER.debug(
                        "Delaying idle check for %s (cooldown %.1fs remaining)",
                        target,
                        _PLAY_COOLDOWN_SEC - elapsed,
                    )
                    self._schedule_idle_check(target, delay)
                    return
            generation = self._control_generation
            self._schedule_idle_check(
                target,
                _IDLE_DEBOUNCE_SEC,
                generation,
            )

        self._unsub_target_listener = self.hass.bus.async_listen(
            "state_changed",
            _on_target_state_change,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Called by coordinator on every data refresh — just re-render state."""
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Playback controls
    # ------------------------------------------------------------------

    async def async_turn_on(self) -> None:
        """Start the default source, including from Alice on/off commands."""
        await self._play_default_source()

    async def _play_default_source(self) -> None:
        """Start the configured source while accepting pre-1.2 station keys."""
        configured = self._entry.options.get(
            CONF_DEFAULT_SOURCE,
            self._entry.options.get(CONF_DEFAULT_STATION, DEFAULT_STATION),
        )
        media_id = normalize_default_source(configured)
        await self.async_play_media(
            media_type=media_type_for_source(media_id),
            media_id=media_id,
        )

    async def async_turn_off(self) -> None:
        """Stop playback without powering down the delegated speaker."""
        self._stop_local(MediaPlayerState.OFF)
        await self._send_to_target("media_player", "media_stop", {})

    async def async_media_play(self) -> None:
        """Resume playback."""
        if self._state == MediaPlayerState.PAUSED and self._current_track:
            await self._send_to_target("media_player", "media_play", {})
            self._state = MediaPlayerState.PLAYING
            self.async_write_ha_state()
        elif self._state in (MediaPlayerState.IDLE, MediaPlayerState.OFF):
            await self._play_default_source()

    async def async_media_pause(self) -> None:
        """Pause playback."""
        await self._send_to_target("media_player", "media_pause", {})
        self._state = MediaPlayerState.PAUSED
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        """Stop playback."""
        self._stop_local(MediaPlayerState.IDLE)
        await self._send_to_target("media_player", "media_stop", {})

    async def async_media_next_track(self) -> None:
        """Skip to next track."""
        generation = self._new_control_generation()
        await self._advance_queue(generation)

    async def async_media_previous_track(self) -> None:
        """Go to previous track."""
        generation = self._new_control_generation()
        if self._queue_pos > 0:
            self._queue_pos -= 1
            await self._play_current_track(generation)
        self.async_write_ha_state()

    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Enable/disable shuffle."""
        self._shuffle = shuffle
        self.async_write_ha_state()

    async def async_media_seek(self, position: float) -> None:
        """Seek to position (seconds) in the current track."""
        track = self._current_track
        if not track:
            return
        duration = self.media_duration
        position = max(0.0, min(position, duration) if duration else position)

        generation = self._new_control_generation()
        session = self._stream_manager.start(self._entry.entry_id)
        stream_url = self._build_stream_url(
            track["id"], session, seek_seconds=position
        )
        target = self._target_player
        if not target:
            self._stream_manager.stop(self._entry.entry_id)
            return
        try:
            await self.hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": target,
                    "media_content_id": stream_url,
                    "media_content_type": "music",
                },
                blocking=True,
            )
        except Exception as err:
            _LOGGER.error("Seek: play_media to %s failed: %s", target, err)
            self._stream_manager.stop(self._entry.entry_id)
            return

        if generation != self._control_generation:
            self._stream_manager.stop(self._entry.entry_id)
            return

        self._play_started_at = dt_util.utcnow() - timedelta(seconds=position)
        self._last_play_command_at = dt_util.utcnow()
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
          station_id:<raw_station_id>     — raw station id
          playlist:<uid>:<kind>           — user playlist
          liked:tracks                    — liked tracks
          track:<track_id>                — single track
        """
        _LOGGER.debug("play_media called: type=%s id=%s", media_type, media_id)

        if media_id.startswith("station:"):
            generation = self._new_control_generation()
            station_key = media_id[len("station:"):]
            station_cfg = PREDEFINED_STATIONS.get(station_key)
            if station_cfg:
                await self._load_station(
                    station_cfg["station_id"],
                    station_cfg["mood_energy"],
                    generation,
                )
            else:
                _LOGGER.warning("Unknown station key: %s", station_key)
            return

        if media_id.startswith("station_id:"):
            generation = self._new_control_generation()
            raw_id = media_id[len("station_id:"):]
            await self._load_station(raw_id, None, generation)
            return

        if media_id.startswith("playlist:"):
            generation = self._new_control_generation()
            parts = media_id[len("playlist:"):].split(":")
            if len(parts) == 2:
                uid, kind = int(parts[0]), int(parts[1])
                await self._load_playlist(uid, kind, generation)
            return

        if media_id.startswith("liked:"):
            generation = self._new_control_generation()
            await self._load_liked_tracks(generation)
            return

        if media_id.startswith("track:"):
            generation = self._new_control_generation()
            track_id = media_id[len("track:"):]
            await self._play_single_track(track_id, generation)
            return

        _LOGGER.warning("Unrecognised media_id: %s", media_id)

    # ------------------------------------------------------------------
    # Loading sources
    # ------------------------------------------------------------------

    async def _load_station(
        self,
        station_id: str,
        mood_energy: str | None,
        generation: int,
    ) -> None:
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

        if generation != self._control_generation:
            return
        if not tracks:
            _LOGGER.warning("No tracks returned for station %s", station_id)
            return

        self._queue = tracks
        self._queue_pos = 0
        if self._shuffle:
            import random
            random.shuffle(self._queue)
        await self._play_current_track(generation)

    def _fetch_station_tracks(
        self,
        station_id: str,
        mood_energy: str | None,
    ) -> list[dict]:
        """Synchronously fetch tracks from a rotor station."""
        settings = None
        if mood_energy:
            try:
                from yandex_music import StationSettings2
                settings = StationSettings2(
                    mood_energy=mood_energy,
                    diversity="default",
                )
            except ImportError:
                # Older/newer yandex_music builds may expose this class differently
                try:
                    import yandex_music as _ym
                    _cls = getattr(_ym, "StationSettings2", None) or getattr(
                        getattr(_ym, "models", None), "StationSettings2", None
                    )
                    if _cls:
                        settings = _cls(mood_energy=mood_energy, diversity="default")
                    else:
                        _LOGGER.warning(
                            "StationSettings2 not found in yandex_music — "
                            "playing station %s without mood filter",
                            station_id,
                        )
                except Exception:
                    _LOGGER.warning(
                        "Cannot apply mood filter for station %s — "
                        "playing without it",
                        station_id,
                    )

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

    async def _load_playlist(self, uid: int, kind: int, generation: int) -> None:
        """Load tracks from a user playlist."""
        try:
            tracks = await self.hass.async_add_executor_job(
                self._fetch_playlist_tracks, uid, kind
            )
        except Exception as err:
            _LOGGER.error("Failed to load playlist %s:%s: %s", uid, kind, err)
            return

        if generation != self._control_generation or not tracks:
            return

        self._current_station_id = None
        self._queue = tracks
        self._queue_pos = 0
        if self._shuffle:
            import random
            random.shuffle(self._queue)
        await self._play_current_track(generation)

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

    async def _load_liked_tracks(self, generation: int) -> None:
        """Load liked tracks."""
        try:
            tracks = await self.hass.async_add_executor_job(self._fetch_liked_tracks)
        except Exception as err:
            _LOGGER.error("Failed to load liked tracks: %s", err)
            return

        if generation != self._control_generation or not tracks:
            return

        self._current_station_id = None
        self._queue = tracks
        self._queue_pos = 0
        if self._shuffle:
            import random
            random.shuffle(self._queue)
        await self._play_current_track(generation)

    def _fetch_liked_tracks(self) -> list[dict]:
        """Synchronously fetch liked tracks."""
        liked = self._coordinator.client.users_likes_tracks()
        if not liked:
            return []
        track_shorts = liked.fetch_tracks()
        return [_track_to_dict(t) for t in track_shorts if t]

    async def _play_single_track(self, track_id: str, generation: int) -> None:
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

        if generation != self._control_generation:
            return
        if track_info:
            self._queue = [track_info]
            await self._play_current_track(generation)

    def _fetch_track_info(self, track_id: str) -> dict | None:
        """Synchronously fetch a single track."""
        tracks = self._coordinator.client.tracks([track_id])
        if tracks:
            return _track_to_dict(tracks[0])
        return None

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    async def _advance_queue(self, generation: int | None = None) -> None:
        """Move to the next track, refilling from station if needed."""
        if generation is None:
            generation = self._control_generation
        if generation != self._control_generation:
            return
        if not self._queue:
            self._stream_manager.stop(self._entry.entry_id)
            self._state = MediaPlayerState.IDLE
            self._play_started_at = None
            self.async_write_ha_state()
            return

        self._queue_pos += 1

        # Refill from station when near the end
        if (
            self._current_station_id
            and self._queue_pos >= len(self._queue) - 3
        ):
            self.hass.async_create_task(self._refill_station_queue())

        if self._queue_pos >= len(self._queue):
            if self._current_station_id:
                # Wait briefly for refill
                await asyncio.sleep(1)
            if generation != self._control_generation:
                return
            if self._queue_pos >= len(self._queue):
                self._stream_manager.stop(self._entry.entry_id)
                self._state = MediaPlayerState.IDLE
                self._play_started_at = None
                self.async_write_ha_state()
                return

        await self._play_current_track(generation)

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
                _LOGGER.debug(
                    "Refilled station queue, total tracks: %d",
                    len(self._queue),
                )
        except Exception as err:
            _LOGGER.error("Failed to refill queue: %s", err)

    async def _play_current_track(self, generation: int | None = None) -> None:
        """Build a local proxy URL and send it to the target media player."""
        if generation is not None and generation != self._control_generation:
            return
        track = self._current_track
        if not track:
            self._state = MediaPlayerState.IDLE
            self.async_write_ha_state()
            return

        # Build a local HA proxy URL so that Yamaha/DLNA devices can fetch
        # audio from our HA server rather than directly from Yandex.
        session = self._stream_manager.start(self._entry.entry_id)
        stream_url = self._build_stream_url(track["id"], session)
        _LOGGER.debug(
            "Playing track '%s — %s' via %s",
            track.get("artist"),
            track.get("title"),
            stream_url,
        )

        target = self._target_player
        if target:
            try:
                await self.hass.services.async_call(
                    "media_player",
                    "play_media",
                    {
                        "entity_id": target,
                        "media_content_id": stream_url,
                        "media_content_type": "music",
                    },
                    blocking=True,
                )
                _LOGGER.debug("play_media sent to %s OK", target)
            except Exception as err:
                _LOGGER.error(
                    "play_media to %s failed: %s — "
                    "if yamaha_musiccast ignores HTTP URLs, add the Yamaha as a "
                    "dlna_dmr entity and use that as target_player instead.",
                    target, err,
                )
                self._stream_manager.stop(self._entry.entry_id)
                self._state = MediaPlayerState.IDLE
                self.async_write_ha_state()
                return
        else:
            _LOGGER.warning(
                "No target_player configured. Set one in integration options. "
                "Stream URL: %s",
                stream_url,
            )
            self._stream_manager.stop(self._entry.entry_id)
            self._state = MediaPlayerState.IDLE
            self.async_write_ha_state()
            return

        if generation is not None and generation != self._control_generation:
            self._stream_manager.stop(self._entry.entry_id)
            return

        now = dt_util.utcnow()
        self._play_started_at = now
        self._last_play_command_at = now
        self._state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    def _build_stream_url(
        self,
        track_id: str,
        session: str,
        seek_seconds: float = 0,
    ) -> str:
        """Build a local HTTP proxy URL for the given track_id.

        The URL must be reachable by the target device (Yamaha, Chromecast, …)
        on the local network.  We force HTTP because many DLNA/UPnP renderers
        cannot verify self-signed HA TLS certificates.
        """
        try:
            base = get_url(
                self.hass,
                allow_internal=True,
                allow_external=False,
                allow_ip=True,
            )
        except Exception:
            base = "http://homeassistant.local:8123"

        # Yamaha MusicCast and most DLNA renderers don't support HTTPS with
        # a self-signed cert — downgrade to HTTP on the same port.
        if base.startswith("https://"):
            base = "http://" + base[8:]

        # track_id may contain ":" (e.g. "12345:678") — encode it
        safe_id = track_id.replace(":", "_")
        url = f"{base}/api/yandex_music/stream/{self._entry.entry_id}/{safe_id}"
        query = {"session": session}
        if seek_seconds > 0:
            query["t"] = str(int(seek_seconds))
        url += f"?{urlencode(query)}"
        _LOGGER.debug(
            "Built stream URL for %s (session token omitted from log)",
            track_id,
        )
        return url

    async def _send_to_target(self, domain: str, service: str, data: dict) -> None:
        """Call a service on the target media player."""
        target = self._target_player
        if not target:
            return
        await self.hass.services.async_call(
            domain,
            service,
            {"entity_id": target, **data},
            blocking=True,
        )

    @property
    def _stream_manager(self) -> YandexMusicStreamManager:
        """Return the stream manager shared by all integration entries."""
        return self.hass.data[DOMAIN][DATA_STREAM_MANAGER]

    def _new_control_generation(self) -> int:
        """Invalidate pending queue commands and return the new generation."""
        self._cancel_idle_check()
        self._control_generation += 1
        return self._control_generation

    def _cancel_idle_check(self) -> None:
        """Cancel a pending debounced idle-state decision."""
        task = self._idle_check_task
        self._idle_check_task = None
        if task is None or task.done():
            return
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if task is not current:
            task.cancel()

    def _schedule_idle_check(
        self,
        target: str,
        delay: float,
        generation: int | None = None,
    ) -> None:
        """Schedule one delayed check for a target that reported idle."""
        self._cancel_idle_check()
        if generation is None:
            generation = self._control_generation
        task = self.hass.async_create_task(
            self._handle_target_idle(target, generation, delay)
        )
        self._idle_check_task = task

        def _clear_idle_task(done_task: asyncio.Task) -> None:
            if self._idle_check_task is done_task:
                self._idle_check_task = None

        task.add_done_callback(_clear_idle_task)

    def _stop_local(self, state: MediaPlayerState) -> None:
        """Stop proxying and update local state immediately."""
        self._new_control_generation()
        self._stream_manager.stop(self._entry.entry_id)
        self._state = state
        self._play_started_at = None
        self._last_play_command_at = None
        self.async_write_ha_state()

    async def _handle_target_idle(
        self,
        target: str,
        generation: int,
        delay: float,
    ) -> None:
        """Distinguish a completed track from an external stop/power-off."""
        await asyncio.sleep(delay)
        if generation != self._control_generation:
            return

        target_state = self.hass.states.get(target)
        if target_state is not None and target_state.state not in {
            "idle",
            "off",
            "unavailable",
            "unknown",
        }:
            return
        if target_state is not None and target_state.state in {
            "off",
            "unavailable",
            "unknown",
        }:
            self._stop_local(
                MediaPlayerState.OFF
                if target_state.state == "off"
                else MediaPlayerState.IDLE
            )
            return

        elapsed = 0.0
        if self._last_play_command_at is not None:
            elapsed = (
                dt_util.utcnow() - self._last_play_command_at
            ).total_seconds()
        duration = self.media_duration
        if duration and elapsed < max(
            _PLAY_COOLDOWN_SEC,
            duration - _TRACK_END_TOLERANCE_SEC,
        ):
            _LOGGER.debug(
                "Target player became idle %.0fs into a %.0fs track; "
                "treating it as an external stop",
                elapsed,
                duration,
            )
            self._stop_local(MediaPlayerState.IDLE)
            return

        _LOGGER.debug("Target player finished track after %.0fs; advancing", elapsed)
        await self._advance_queue(generation)

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
        static_station_ids = {
            cfg["station_id"]
            for cfg in PREDEFINED_STATIONS.values()
            if cfg.get("mood_energy") is None
        }
        data = self._coordinator.data or {}
        for station in data.get("stations", []):
            station_id = station.get("station_id")
            title = station.get("title")
            if not station_id or not title or station_id in static_station_ids:
                continue
            children.append(
                BrowseMedia(
                    title=title,
                    media_class="music",
                    media_content_type=MEDIA_TYPE_STATION,
                    media_content_id=f"station_id:{station_id}",
                    can_play=True,
                    can_expand=False,
                    thumbnail=station.get("image_url"),
                )
            )
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
    album_name = (
        albums[0].title
        if albums and getattr(albums[0], "title", None)
        else None
    )

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
