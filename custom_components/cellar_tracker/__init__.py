"""Cellar Tracker integration.

Set up from a config entry created in the UI (config_flow.py). YAML is not
supported: a leftover `cellar_tracker:` block only makes Home Assistant log an
error and raise its own config_entry_only repair issue. See
docs/superpowers/specs/2026-09-30-config-flow-design.md.
"""

from __future__ import annotations

import logging

import homeassistant.helpers.config_validation as cv
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import CellarTrackerConfigEntry, CellarTrackerCoordinator
from .migrate import async_cleanup_registry
from .naming import expected_unique_ids

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: CellarTrackerConfigEntry) -> bool:
    """Set up Cellar Tracker from a config entry."""
    coordinator = CellarTrackerCoordinator(hass, entry)
    # Raises ConfigEntryNotReady (HA retries with backoff) or
    # ConfigEntryAuthFailed (HA starts reauth).
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Only clean the registry against data we trust. A fetch can "succeed"
    # with zero rows if CellarTracker returns a maintenance page or an error
    # body: csv.DictReader yields nothing, no exception is raised, and
    # expected_unique_ids() would then contain only the 13 fixed ids --
    # deleting every per-value entity, irreversibly, along with any renames
    # and area assignments the user made.
    if coordinator.data.total_bottles and coordinator.data.low:
        removed = await async_cleanup_registry(hass, expected_unique_ids(coordinator.data))
        _LOGGER.debug("Registry cleanup removed %s stale entities", removed)
    else:
        _LOGGER.warning(
            "Skipping registry cleanup: the inventory came back empty or without recognised columns"
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CellarTrackerConfigEntry) -> bool:
    """Unload a config entry. The coordinator shuts itself down via async_on_unload."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
