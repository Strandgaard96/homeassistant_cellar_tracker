"""Remove entities the old per-value model registered.

Old entities have unique_ids and no config entry, so Home Assistant writes
`unavailable` for each of them at every start, forever -- the 30-day orphan
purge only applies to entries already marked deleted. Left alone, upgrading
users inherit roughly 400 grey entities to delete by hand.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def stale_unique_ids(registered: set[str], expected: set[str]) -> set[str]:
    """Registered IDs the new model no longer provides."""
    return registered - expected


async def async_cleanup_registry(hass: HomeAssistant, expected: set[str]) -> int:
    """Delete this platform's registry entries that are no longer provided.

    Returns the number removed.
    """
    registry = er.async_get(hass)
    ours = {
        entry.unique_id: entry.entity_id
        for entry in registry.entities.values()
        if entry.platform == DOMAIN
    }
    stale = stale_unique_ids(set(ours), expected)
    for unique_id in stale:
        registry.async_remove(ours[unique_id])
    if stale:
        _LOGGER.info(
            "Removed %s Cellar Tracker entities left over from the previous "
            "sensor model", len(stale),
        )
    return len(stale)
