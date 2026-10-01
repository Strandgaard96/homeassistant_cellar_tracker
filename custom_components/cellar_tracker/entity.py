"""Base entity for Cellar Tracker."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CellarTrackerCoordinator


class CellarTrackerEntity(CoordinatorEntity[CellarTrackerCoordinator]):
    """Shared device, naming and availability policy.

    has_entity_name prefixes the device name, so "total bottles" still
    becomes sensor.cellar_tracker_total_bottles and the friendly name
    "Cellar Tracker total bottles", exactly as before the config flow.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: CellarTrackerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name="Cellar Tracker",
            manufacturer="CellarTracker!",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.cellartracker.com",
        )

    @property
    def available(self) -> bool:
        """Stay available on stale data once any fetch has succeeded.

        CoordinatorEntity.available defaults to last_update_success, which
        would blank every entity on one failed refresh. Wrong for an
        inventory that changes a few times a week.
        """
        return self.coordinator.ever_succeeded
