"""Fetch scheduling for Cellar Tracker.

Replaces the previous hand-rolled double Throttle. That arrangement only
stamped its timestamp on success, so during an outage every entity's poll
re-attempted the fetch -- 47 attempts per 30 seconds, each logging an error.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from cellartracker import cellartracker
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .aggregate import CellarData, aggregate
from .const import DEFAULT_SCORE_BANDS, DOMAIN

_LOGGER = logging.getLogger(__name__)


class CellarTrackerCoordinator(DataUpdateCoordinator[CellarData]):
    """Owns the CellarTracker fetch and the aggregation that follows it."""

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        scan_interval: timedelta,
        score_bands=DEFAULT_SCORE_BANDS,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name=DOMAIN,
            update_interval=scan_interval,
            always_update=False,
        )
        self._username = username
        self._password = password
        self._score_bands = score_bands
        self._ever_succeeded = False

    def _fetch(self) -> CellarData:
        """Blocking fetch plus aggregation. Runs in an executor thread."""
        client = cellartracker.CellarTracker(self._username, self._password)
        return aggregate(client.get_inventory(), self._score_bands)

    async def _async_update_data(self) -> CellarData:
        try:
            data = await self.hass.async_add_executor_job(self._fetch)
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
