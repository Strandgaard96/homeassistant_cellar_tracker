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

from .const import DEFAULT_SCAN_INTERVAL, DEFAULT_SCORE_BANDS, DOMAIN, MIN_SCAN_INTERVAL
from .coordinator import CellarTrackerCoordinator
from .migrate import async_cleanup_registry
from .naming import expected_unique_ids

_LOGGER = logging.getLogger(__name__)

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
    await coordinator.async_refresh()
    if not coordinator.last_update_success or coordinator.data is None:
        _LOGGER.error(
            "Initial CellarTracker fetch failed; not setting up. Error: %s",
            coordinator.last_exception,
        )
        return False

    hass.data[DOMAIN] = coordinator
    await coordinator.async_register_shutdown()

    # Only clean the registry against data we trust. A fetch can "succeed"
    # with zero rows if CellarTracker returns a maintenance page or an error
    # body: csv.DictReader yields nothing, no exception is raised, and
    # expected_unique_ids() would then contain only the 13 fixed ids --
    # deleting all 34 per-value entities, irreversibly, along with any
    # renames and area assignments the user made.
    if coordinator.data.total_bottles and coordinator.data.low:
        removed = await async_cleanup_registry(hass, expected_unique_ids(coordinator.data))
        _LOGGER.debug("Registry cleanup removed %s stale entities", removed)
    else:
        _LOGGER.warning(
            "Skipping registry cleanup: the inventory came back empty or without recognised columns"
        )

    hass.async_create_task(hdisco.async_load_platform(hass, "sensor", DOMAIN, {}, config))
    return True
