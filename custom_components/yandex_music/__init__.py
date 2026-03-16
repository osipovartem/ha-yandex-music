"""Yandex Music integration for Home Assistant."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_TOKEN, DOMAIN, PLATFORMS, UPDATE_INTERVAL_MINUTES
from .stream import YandexMusicStreamView

_LOGGER = logging.getLogger(__name__)

_stream_view_registered = False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Yandex Music from a config entry."""
    global _stream_view_registered

    token = entry.data[CONF_TOKEN]

    coordinator = YandexMusicCoordinator(hass, token)

    try:
        await coordinator.async_initialize()
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot connect to Yandex Music: {err}") from err

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Register HTTP streaming view once (survives multiple config entries)
    if not _stream_view_registered:
        hass.http.register_view(YandexMusicStreamView())
        _stream_view_registered = True
        _LOGGER.debug("Registered Yandex Music stream view")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


class YandexMusicCoordinator(DataUpdateCoordinator):
    """Coordinator to manage Yandex Music data updates."""

    def __init__(self, hass: HomeAssistant, token: str) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self._token = token
        self.client = None
        self.account_info: dict = {}

    async def async_initialize(self) -> None:
        """Initialize the Yandex Music client."""
        from yandex_music import Client

        self.client = await self.hass.async_add_executor_job(
            self._init_client
        )

    def _init_client(self):
        """Synchronously initialize and return the client."""
        from yandex_music import Client

        client = Client(self._token).init()
        return client

    async def _async_update_data(self) -> dict:
        """Fetch data from Yandex Music."""
        try:
            return await self.hass.async_add_executor_job(self._fetch_data)
        except Exception as err:
            raise UpdateFailed(f"Error fetching Yandex Music data: {err}") from err

    def _fetch_data(self) -> dict:
        """Synchronously fetch playlists and account info."""
        playlists = self.client.users_playlists_list() or []
        account_status = self.client.account_status()

        return {
            "playlists": [
                {
                    "uid": p.uid,
                    "kind": p.kind,
                    "title": p.title or f"Плейлист {p.kind}",
                    "track_count": p.track_count or 0,
                    "cover_uri": _cover_url(getattr(p, "cover", None)),
                }
                for p in playlists
            ],
            "account": {
                "uid": account_status.account.uid if account_status else None,
                "login": account_status.account.login if account_status else "unknown",
            },
        }


def _cover_url(cover) -> str | None:
    """Extract a usable HTTPS cover URL from a Yandex Music cover object."""
    if cover is None:
        return None
    uri = getattr(cover, "uri", None)
    if uri:
        if uri.startswith("//"):
            uri = "https:" + uri
        return uri.replace("%%", "200x200")
    return None
