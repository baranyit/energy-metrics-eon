"""Config flow for Energy Monitoring for E.ON Hungary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import BridgeAuthError, BridgeClient, BridgeError
from .const import (
    CONF_EXPORT_COLUMN,
    CONF_IMPORT_COLUMN,
    CONF_INTERVAL_END,
    CONF_POD,
    CONF_SCRIPT_URL,
    CONF_TOKEN,
    DEFAULT_EXPORT_COLUMN,
    DEFAULT_IMPORT_COLUMN,
    DEFAULT_NAME,
    DOMAIN,
    SCRIPT_URL_PREFIX,
)


PLACEHOLDERS = {"script_url_prefix": SCRIPT_URL_PREFIX}


def _schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Required(
                CONF_SCRIPT_URL, default=defaults.get(CONF_SCRIPT_URL, vol.UNDEFINED)
            ): str,
            vol.Required(CONF_TOKEN, default=defaults.get(CONF_TOKEN, vol.UNDEFINED)): str,
            vol.Optional(
                CONF_IMPORT_COLUMN,
                description={
                    "suggested_value": defaults.get(
                        CONF_IMPORT_COLUMN, DEFAULT_IMPORT_COLUMN
                    )
                },
            ): str,
            vol.Optional(
                CONF_EXPORT_COLUMN,
                description={
                    "suggested_value": defaults.get(
                        CONF_EXPORT_COLUMN, DEFAULT_EXPORT_COLUMN
                    )
                },
            ): str,
            vol.Optional(
                CONF_POD,
                description={"suggested_value": defaults.get(CONF_POD, "")},
            ): str,
            vol.Required(
                CONF_INTERVAL_END, default=defaults.get(CONF_INTERVAL_END, False)
            ): bool,
        }
    )


class EonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up or change one metering point."""

    VERSION = 1

    async def _validate(self, user_input: dict[str, Any]) -> dict[str, str]:
        user_input[CONF_SCRIPT_URL] = user_input[CONF_SCRIPT_URL].strip()
        user_input[CONF_TOKEN] = user_input[CONF_TOKEN].strip()
        user_input[CONF_POD] = (user_input.get(CONF_POD) or "").strip()
        if not user_input[CONF_SCRIPT_URL].startswith(SCRIPT_URL_PREFIX):
            return {CONF_SCRIPT_URL: "invalid_url"}
        if not (
            user_input.get(CONF_IMPORT_COLUMN) or user_input.get(CONF_EXPORT_COLUMN)
        ):
            return {"base": "no_columns"}

        client = BridgeClient(
            async_get_clientsession(self.hass),
            user_input[CONF_SCRIPT_URL],
            user_input[CONF_TOKEN],
        )
        try:
            # A cursor in the future: checks URL and token without moving data.
            await client.fetch(int(dt_util.utcnow().timestamp() * 1000) + 86_400_000, 1)
        except BridgeAuthError:
            return {CONF_TOKEN: "invalid_auth"}
        except BridgeError:
            return {"base": "cannot_connect"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._validate(user_input)
            if not errors:
                self._async_abort_entries_match({CONF_NAME: user_input[CONF_NAME]})
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
            description_placeholders=PLACEHOLDERS,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            # The name is part of the statistic ids, so it cannot change.
            user_input[CONF_NAME] = entry.data[CONF_NAME]
            errors = await self._validate(user_input)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=user_input)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or entry.data),
            errors=errors,
            description_placeholders=PLACEHOLDERS,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_TOKEN: user_input[CONF_TOKEN]}
            errors = await self._validate(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            errors=errors,
            description_placeholders=PLACEHOLDERS,
        )
