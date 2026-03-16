"""Config flow for Yandex Music integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEFAULT_STATION,
    CONF_TARGET_PLAYER,
    CONF_TOKEN,
    DEFAULT_STATION,
    DOMAIN,
    PREDEFINED_STATIONS,
)

_LOGGER = logging.getLogger(__name__)

STATION_OPTIONS = [
    selector.SelectOptionDict(value=key, label=val["name"])
    for key, val in PREDEFINED_STATIONS.items()
]


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
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                "token_help": "https://github.com/osipovartem/ha-yandex-music#получение-токена"
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

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TARGET_PLAYER,
                    default=current.get(CONF_TARGET_PLAYER, ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player")
                ),
                vol.Optional(
                    CONF_DEFAULT_STATION,
                    default=current.get(CONF_DEFAULT_STATION, DEFAULT_STATION),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=STATION_OPTIONS,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
