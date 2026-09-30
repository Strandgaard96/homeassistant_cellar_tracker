"""Cellar Tracker sensors.

Two entity shapes, split by cardinality:

  Low-cardinality dimensions (country, type, size, category, location,
  color) get one numeric sensor per distinct value. These work in
  numeric_state triggers, in templates without selectattr gymnastics, and
  in voice assistants.

  Long tails (producer, appellation, store, ...) get one sensor each whose
  `items` attribute carries the breakdown. Templating against these needs
  state_attr(...) | selectattr('name','eq',X) | map(attribute='count')
  | first. That is the accepted cost of not creating 184 entities.
"""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .aggregate import items_payload
from .const import DOMAIN, LOW_CARDINALITY
from .coordinator import CellarTrackerConfigEntry, CellarTrackerCoordinator
from .naming import SLICE_DIMENSIONS, unique_slugs


class _Base(CoordinatorEntity[CellarTrackerCoordinator], SensorEntity):
    """Shared device, naming and availability policy.

    has_entity_name prefixes the device name, so "total bottles" still
    becomes sensor.cellar_tracker_total_bottles and the friendly name
    "total bottles", exactly as before the config flow.
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


class CellarValueSensor(_Base):
    """One distinct value of a low-cardinality dimension. State = bottles."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "bottles"
    _attr_icon = "mdi:bottle-wine"

    def __init__(self, coordinator, dimension: str, value: str, slug: str) -> None:
        super().__init__(coordinator)
        self._dimension = dimension
        self._value = value
        self._attr_unique_id = f"{DOMAIN}_{dimension}_{slug}"
        self._attr_name = f"{dimension} {value}"

    def _item(self):
        for item in self.coordinator.data.low.get(self._dimension, []):
            if item.name == self._value:
                return item
        return None

    @property
    def native_value(self) -> int:
        item = self._item()
        return item.count if item else 0

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        item = self._item()
        if item is None:
            return {}
        total = self.coordinator.data.total_bottles or 1
        return {
            "value_avg": item.value_avg,
            "value_total": round(item.value_avg * item.count, 2),
            "score_avg": item.score_avg,
            "pct": round(100 * item.count / total, 2),
        }


class CellarSliceSensor(_Base):
    """A long-tail dimension. State = distinct values, breakdown in `items`.

    `items` is excluded from the recorder. This is not tidiness: the
    recorder caps serialised attributes at 16384 bytes and stores an empty
    dict for the entity's *whole* attribute set above that, so a 184-item
    producer list would silently blank everything.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:table"
    _unrecorded_attributes = frozenset({"items"})

    def __init__(self, coordinator, dimension: str) -> None:
        super().__init__(coordinator)
        self._dimension = dimension
        self._attr_unique_id = f"{DOMAIN}_by_{dimension}"
        self._attr_name = f"by {dimension}"

    def _items(self):
        return self.coordinator.data.tails.get(self._dimension, [])

    @property
    def native_value(self) -> int:
        return len(self._items())

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        items = self._items()
        return {"items": items_payload(items), "items_total": len(items)}


class CellarScalarSensor(_Base):
    """One of the four cellar-wide numbers."""

    def __init__(self, coordinator, key: str, name: str, **attrs) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_name = name
        for attr, value in attrs.items():
            setattr(self, f"_attr_{attr}", value)

    @property
    def native_value(self):
        return getattr(self.coordinator.data, self._key)


# (key, display name, device_class, state_class, unit, icon).
# CURRENCY means "substitute the cellar's currency at build time".
# Kept module-level so tests/test_sensor_classes.py can check every
# device_class/state_class pairing without constructing a coordinator.
CURRENCY = object()

SCALAR_SPECS = (
    (
        "total_bottles",
        "total bottles",
        None,
        SensorStateClass.MEASUREMENT,
        "bottles",
        "mdi:bottle-wine",
    ),
    # monetary requires TOTAL: sensor/const.py maps MONETARY to {TOTAL}
    # only, and measurement logs a warning on every install.
    (
        "total_value",
        "total value",
        SensorDeviceClass.MONETARY,
        SensorStateClass.TOTAL,
        CURRENCY,
        None,
    ),
    # An average is not a total, so it gets no device_class at all.
    (
        "average_value",
        "average value",
        None,
        SensorStateClass.MEASUREMENT,
        CURRENCY,
        "mdi:cash",
    ),
    (
        "average_score",
        "average score",
        None,
        SensorStateClass.MEASUREMENT,
        "points",
        "mdi:star",
    ),
)


def _scalars(coordinator) -> list[SensorEntity]:
    currency = coordinator.data.currency or None
    entities: list[SensorEntity] = []
    for key, name, device_class, state_class, unit, icon in SCALAR_SPECS:
        attrs: dict[str, object] = {"state_class": state_class}
        if device_class is not None:
            attrs["device_class"] = device_class
        resolved_unit = currency if unit is CURRENCY else unit
        if resolved_unit is not None:
            attrs["native_unit_of_measurement"] = resolved_unit
        if icon is not None:
            attrs["icon"] = icon
        entities.append(CellarScalarSensor(coordinator, key, name, **attrs))
    return entities


def build_entities(coordinator) -> list[SensorEntity]:
    """Every entity this integration provides, for the current data."""
    entities: list[SensorEntity] = []
    for dimension in LOW_CARDINALITY:
        items = coordinator.data.low.get(dimension, [])
        slugs = unique_slugs([item.name for item in items])
        for item in items:
            entities.append(CellarValueSensor(coordinator, dimension, item.name, slugs[item.name]))
    for dimension in SLICE_DIMENSIONS:
        entities.append(CellarSliceSensor(coordinator, dimension))
    entities.extend(_scalars(coordinator))
    return entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CellarTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    async_add_entities(build_entities(entry.runtime_data))
