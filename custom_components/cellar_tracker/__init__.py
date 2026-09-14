"""Cellar Tracker integration.

YAML-configured, so there is no config entry and therefore no device. See
docs/superpowers/specs/2026-09-14-cellar-tracker-dashboard-design.md.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery as hdisco
from homeassistant.helpers.typing import ConfigType

from .const import DEFAULT_SCORE_BANDS, DOMAIN
from .coordinator import CellarTrackerCoordinator
from .migrate import async_cleanup_registry
from .naming import expected_unique_ids

_LOGGER = logging.getLogger(__name__)

MIN_SCAN_INTERVAL = 30
DEFAULT_SCAN_INTERVAL = 3600

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Clamp(min=MIN_SCAN_INTERVAL)
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Cellar Tracker from YAML."""
    conf = config[DOMAIN]
    seconds = conf[CONF_SCAN_INTERVAL]
    _LOGGER.debug("Using scan_interval of %s seconds", seconds)

    coordinator = CellarTrackerCoordinator(
        hass,
        conf[CONF_USERNAME],
        conf[CONF_PASSWORD],
        timedelta(seconds=seconds),
        DEFAULT_SCORE_BANDS,
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN] = coordinator

    await async_cleanup_registry(hass, expected_unique_ids(coordinator.data))

    hass.async_create_task(
        hdisco.async_load_platform(hass, "sensor", DOMAIN, {}, config)
    )
    return True
