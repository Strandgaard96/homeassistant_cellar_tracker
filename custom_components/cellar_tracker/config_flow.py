"""Config flow for Cellar Tracker."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from cellartracker.cellartracker import CellarTracker
from cellartracker.errors import AuthenticationError, CannotConnect
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, FETCH_TIMEOUT, MIN_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

_PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
    }
)

REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR})

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=MIN_SCAN_INTERVAL,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        )
    }
)


async def _async_validate(hass: HomeAssistant, username: str, password: str) -> None:
    """Fetch the inventory once. Raises on bad credentials or no connection.

    An empty inventory is a valid login and passes.
    """

    def _fetch() -> None:
        CellarTracker(username, password).get_inventory()

    async with asyncio.timeout(FETCH_TIMEOUT):
        await hass.async_add_executor_job(_fetch)


async def _async_error_key(hass: HomeAssistant, username: str, password: str) -> str | None:
    """Validate and translate any failure into a form error key."""
    try:
        await _async_validate(hass, username, password)
    except AuthenticationError:
        return "invalid_auth"
    except (CannotConnect, TimeoutError):
        return "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error validating the CellarTracker login")
        return "unknown"
    return None


class CellarTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one CellarTracker account.

    manifest.json sets single_config_entry, so HA aborts a second user or
    import flow with single_instance_allowed before this class is even
    constructed; no step needs _abort_if_unique_id_configured().
    """

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CellarTrackerOptionsFlow:
        return CellarTrackerOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            error = await _async_error_key(self.hass, username, password)
            if error is None:
                await self.async_set_unique_id(username.lower())
                return self.async_create_entry(
                    title=username,
                    data={CONF_USERNAME: username, CONF_PASSWORD: password},
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password only. The username, and so the unique ID, is fixed."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            error = await _async_error_key(self.hass, entry.data[CONF_USERNAME], password)
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: password}
                )
            errors["base"] = error
        # The form's {name} placeholder is filled with entry.title (the
        # username) by ConfigFlow.async_show_form for reauth flows.
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=REAUTH_SCHEMA, errors=errors
        )


class CellarTrackerOptionsFlow(OptionsFlowWithReload):
    """Change the fetch interval. The base class reloads the entry on change."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # NumberSelector yields a float; the coordinator wants whole seconds.
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
