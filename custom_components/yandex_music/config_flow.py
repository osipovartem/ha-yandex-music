"""Config flow for Yandex Music integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEFAULT_PLAYLIST,
    CONF_DEFAULT_SOURCE,
    CONF_DEFAULT_STATION,
    CONF_TARGET_PLAYER,
    CONF_TOKEN,
    DEFAULT_STATION,
    DOMAIN,
    PREDEFINED_STATIONS,
)
from .source_catalog import (
    PLAYLIST_PICKER_VALUE,
    build_default_source_choices,
    build_playlist_choices,
    normalize_default_source,
)

_LOGGER = logging.getLogger(__name__)

class YandexMusicConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Yandex Music."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step — token entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            try:
                login = await self._validate_token(token)
            except Exception:
                _LOGGER.exception("Error validating Yandex Music token")
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"yandex_music_{login}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Yandex Music ({login})",
                    data={CONF_TOKEN: token},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                "token_help": (
                    "https://github.com/osipovartem/"
                    "ha-yandex-music#getting-a-token"
                )
            },
        )

    async def _validate_token(self, token: str) -> str:
        """Validate token and return account login."""
        def _init():
            from yandex_music import Client

            client = Client(token).init()
            status = client.account_status()
            return status.account.login

        return await self.hass.async_add_executor_job(_init)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return YandexMusicOptionsFlow(config_entry)


class YandexMusicOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Yandex Music."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._current_source = config_entry.options.get(
            CONF_DEFAULT_SOURCE,
            config_entry.options.get(CONF_DEFAULT_STATION, DEFAULT_STATION),
        )
        self._pending_options: dict[str, Any] = {}

    def _catalog_data(self) -> dict[str, Any]:
        """Return the latest account catalog cached by the coordinator."""
        coordinator = self.hass.data.get(DOMAIN, {}).get(
            self._config_entry.entry_id
        )
        return getattr(coordinator, "data", None) or {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            if user_input.get(CONF_DEFAULT_SOURCE) == PLAYLIST_PICKER_VALUE:
                self._pending_options = user_input
                return await self.async_step_playlist()
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options
        normalized_current = normalize_default_source(self._current_source)
        selected_source = (
            PLAYLIST_PICKER_VALUE
            if normalized_current.startswith("playlist:")
            else normalized_current
        )
        source_options = [
            selector.SelectOptionDict(value=value, label=label)
            for value, label in build_default_source_choices(
                PREDEFINED_STATIONS,
                self._catalog_data(),
                self._current_source,
            )
        ]

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TARGET_PLAYER,
                    default=current.get(CONF_TARGET_PLAYER, ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player")
                ),
                vol.Optional(
                    CONF_DEFAULT_SOURCE,
                    default=selected_source,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=source_options,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        # The personal-playlist choice opens a second selector after this form.
        # Tell the frontend this may not be the final step so it renders a
        # "Next" action instead of the misleading "Submit" action.
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            last_step=False,
        )

    async def async_step_playlist(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Select a personal playlist on a separate compact screen."""
        if user_input is not None:
            options = dict(self._pending_options)
            options[CONF_DEFAULT_SOURCE] = user_input[CONF_DEFAULT_PLAYLIST]
            return self.async_create_entry(title="", data=options)

        playlist_choices = build_playlist_choices(
            self._catalog_data(),
            self._current_source,
        )
        playlist_options = [
            selector.SelectOptionDict(value=value, label=label)
            for value, label in playlist_choices
        ]
        normalized_current = normalize_default_source(self._current_source)
        default_playlist = (
            normalized_current
            if normalized_current.startswith("playlist:")
            else playlist_choices[0][0]
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEFAULT_PLAYLIST,
                    default=default_playlist,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=playlist_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="playlist",
            data_schema=schema,
            last_step=True,
        )
