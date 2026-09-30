"""Fetch scheduling for Cellar Tracker.

Replaces the previous hand-rolled double Throttle. That arrangement only
stamped its timestamp on success, so during an outage every entity's poll
re-attempted the fetch -- 47 attempts per 30 seconds, each logging an error.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from cellartracker.cellartracker import CellarTracker
from cellartracker.errors import AuthenticationError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .aggregate import CellarData, aggregate
from .const import DEFAULT_SCAN_INTERVAL, DEFAULT_SCORE_BANDS, DOMAIN, FETCH_TIMEOUT

_LOGGER = logging.getLogger(__name__)

type CellarTrackerConfigEntry = ConfigEntry[CellarTrackerCoordinator]


class CellarTrackerCoordinator(DataUpdateCoordinator[CellarData]):
    """Owns the CellarTracker fetch and the aggregation that follows it."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        score_bands=DEFAULT_SCORE_BANDS,
    ) -> None:
        seconds = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        _LOGGER.debug("Using scan_interval of %s seconds", seconds)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=seconds),
            always_update=False,
        )
        self._username = entry.data[CONF_USERNAME]
        self._password = entry.data[CONF_PASSWORD]
        self._score_bands = score_bands
        self._ever_succeeded = False

    def _fetch(self) -> CellarData:
        """Blocking fetch plus aggregation. Runs in an executor thread."""
        client = CellarTracker(self._username, self._password)
        return aggregate(client.get_inventory(), self._score_bands)

    async def _async_update_data(self) -> CellarData:
        try:
            async with asyncio.timeout(FETCH_TIMEOUT):
                data = await self.hass.async_add_executor_job(self._fetch)
        except AuthenticationError as err:
            # Must stay ahead of the generic clause, or reauth never starts.
            raise ConfigEntryAuthFailed("CellarTracker rejected the credentials") from err
        except Exception as err:
            raise UpdateFailed(f"CellarTracker update failed: {err}") from err
        self._ever_succeeded = True
        return data

    @property
    def ever_succeeded(self) -> bool:
        """True once any fetch has succeeded.

        Entities use this rather than last_update_success so a transient
        CellarTracker outage shows stale inventory instead of blanking every
        entity. An inventory is not a live reading; yesterday's is still
        useful.
        """
        return self._ever_succeeded
