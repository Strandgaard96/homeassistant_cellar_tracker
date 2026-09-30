# Config Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace YAML-only setup of the `cellar_tracker` custom integration with a UI config flow (user, reauth, options), keeping every existing entity ID.

**Architecture:** Setup moves from `async_setup` + discovery to `async_setup_entry` with the coordinator in `entry.runtime_data`. `config_flow.py` validates credentials by fetching the inventory. YAML is dropped: `CONFIG_SCHEMA` becomes `cv.config_entry_only_config_schema`, so a leftover block only raises HA's own repair issue. Entities gain a service device and `has_entity_name`; unique IDs are unchanged so HA adopts existing registry entries.

**Tech Stack:** Home Assistant 2026.2.3 custom integration, Python 3.13, `cellartracker` 1.1.1, pandas, pytest + `pytest-homeassistant-custom-component` 0.13.316, ruff, ty, uv.

**Spec:** `docs/superpowers/specs/2026-09-30-config-flow-design.md`

## Global Constraints

- Domain `cellar_tracker`; entity unique IDs unchanged: `cellar_tracker_{dimension}_{slug}`, `cellar_tracker_by_{dimension}`, `cellar_tracker_{key}`.
- One config entry per HA instance: manifest `"single_config_entry": true`.
- Config entry unique ID: `username.lower()`, set by the user step.
- Credentials in `entry.data` (`username`, `password`); `scan_interval` (int seconds) in `entry.options`, default 3600, minimum 30.
- Network fetch timeout: 60 s (`FETCH_TIMEOUT`), in both the flow and the coordinator.
- Device: name `Cellar Tracker`, manufacturer `CellarTracker!`, `DeviceEntryType.SERVICE`, `configuration_url` `https://www.cellartracker.com`, identifiers `{(DOMAIN, entry.entry_id)}`.
- `translations/en.json` is full flat text; no `[%key:...%]` references.
- `hacs.json` minimum HA: 2026.2.0.
- Before every commit: `uvx ruff check .`, `uvx ruff format .`, `uvx ty check`, and the test command below all come back clean.
- Test command (from Task 1 on):
  `uv run --with pytest-homeassistant-custom-component --with cellartracker --with pandas pytest tests -q`
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A YAML-era user who renamed an entity's `entity_id` upgrades: the entity keeps the renamed ID and joins the config entry (test in Task 2).
2. CellarTracker is down when HA starts: the entry goes to `SETUP_RETRY` and recovers, instead of staying dead until restart (test in Task 2).
3. An entity left from the old sensor model, registered without a config entry, is still removed by registry cleanup (test in Task 2).
4. A user signs up as `Alice` and later reauths: the entry unique ID is `alice` and the stored username is untouched by reauth (tests in Task 3).
5. The user forgets to delete the old `cellar_tracker:` YAML block: HA shows the `config_entry_only_cellar_tracker` repair issue, creates no entry and never contacts CellarTracker with those credentials (test in Task 4).

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `pyproject.toml` | add `asyncio_mode = "auto"` | 1 |
| `tests/conftest.py` (new) | autouse custom-integration fixture, `mock_client`, `config_entry` fixtures | 1, 3 |
| `custom_components/cellar_tracker/const.py` | add `DEFAULT_SCAN_INTERVAL`, `MIN_SCAN_INTERVAL`, `FETCH_TIMEOUT` | 1 |
| `custom_components/cellar_tracker/coordinator.py` | coordinator built from a config entry; error mapping | 2 |
| `custom_components/cellar_tracker/__init__.py` | `CONFIG_SCHEMA` (config-entry only), `async_setup_entry`, `async_unload_entry` | 2, 4 |
| `custom_components/cellar_tracker/sensor.py` | device info, `has_entity_name`, `async_setup_entry` | 2 |
| `tests/test_init.py` (new) | entry setup, retry, unload, registry continuity, reauth trigger, YAML rejection | 2, 3, 4 |
| `custom_components/cellar_tracker/config_flow.py` (new) | user, reauth, options flows | 3 |
| `custom_components/cellar_tracker/strings.json` (new) | UI text source (core-style) | 3 |
| `custom_components/cellar_tracker/translations/en.json` (new) | identical copy of `strings.json`, loaded by HA | 3 |
| `custom_components/cellar_tracker/manifest.json` | config flow flags, version bump | 3, 5 |
| `tests/test_config_flow.py` (new) | flow tests | 3 |
| `README.md`, `CLAUDE.md` | docs | 1, 5 |

---

### Task 1: Test harness and shared constants

**Files:**
- Modify: `pyproject.toml` (the `[tool.pytest.ini_options]` table at the end)
- Create: `tests/conftest.py`
- Modify: `custom_components/cellar_tracker/const.py` (append)
- Modify: `CLAUDE.md` (Commands block)

**Interfaces:**
- Produces: `const.DEFAULT_SCAN_INTERVAL: int = 3600`, `const.MIN_SCAN_INTERVAL: int = 30`, `const.FETCH_TIMEOUT: int = 60`; pytest fixture `enable_custom_integrations` applied to every test.

- [ ] **Step 1: Turn on asyncio auto mode**

In `pyproject.toml`, replace

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

with

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
# pytest-homeassistant-custom-component's `hass` fixture is a plain
# @pytest.fixture over an async function; strict mode would ignore it.
asyncio_mode = "auto"
```

- [ ] **Step 2: Create `tests/conftest.py`**

```python
"""Shared fixtures.

pytest-homeassistant-custom-component refuses to load anything from
custom_components/ unless `enable_custom_integrations` is requested, and its
own fixture is not autouse.
"""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
```

- [ ] **Step 3: Add the constants**

Append to `custom_components/cellar_tracker/const.py`:

```python

# Seconds between inventory fetches. The inventory changes a few times a
# week, so an hour is plenty; 30 s is a floor against hammering the site.
DEFAULT_SCAN_INTERVAL = 3600
MIN_SCAN_INTERVAL = 30

# cellartracker calls requests.get with no timeout. This bounds the await,
# not the executor thread: a hung socket keeps its thread until it gives up.
FETCH_TIMEOUT = 60
```

- [ ] **Step 4: Point `__init__.py` at the shared constants**

In `custom_components/cellar_tracker/__init__.py`, delete the two lines

```python
MIN_SCAN_INTERVAL = 30
DEFAULT_SCAN_INTERVAL = 3600
```

and change the import

```python
from .const import DEFAULT_SCORE_BANDS, DOMAIN
```

to

```python
from .const import DEFAULT_SCAN_INTERVAL, DEFAULT_SCORE_BANDS, DOMAIN, MIN_SCAN_INTERVAL
```

- [ ] **Step 5: Update the test command in CLAUDE.md**

In `CLAUDE.md`, replace the line

```bash
uv run --with homeassistant --with cellartracker --with pytest --with pandas pytest tests -q   # tests
```

with

```bash
uv run --with pytest-homeassistant-custom-component --with cellartracker --with pandas pytest tests -q   # tests
```

and replace "All three must come back clean before committing." with "All of these must come back clean before committing."

- [ ] **Step 6: Run the suite**

Run: `uv run --with pytest-homeassistant-custom-component --with cellartracker --with pandas pytest tests -q`
Expected: `36 passed`

- [ ] **Step 7: Lint, format, type-check**

Run: `uvx ruff check . && uvx ruff format . && uvx ty check`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml tests/conftest.py custom_components/cellar_tracker/const.py custom_components/cellar_tracker/__init__.py CLAUDE.md
git commit -m "test: switch to pytest-homeassistant-custom-component harness

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Config-entry setup, coordinator and entities

After this task the integration sets up from a config entry. YAML is still accepted by the old schema but configures nothing until Task 4 removes it; the branch is not releasable in between.

**Files:**
- Modify: `custom_components/cellar_tracker/coordinator.py` (whole file)
- Modify: `custom_components/cellar_tracker/__init__.py` (whole file)
- Modify: `custom_components/cellar_tracker/sensor.py:17-60, 94-125, 131-155, 193-198`
- Modify: `tests/conftest.py` (add fixtures)
- Create: `tests/test_init.py`

**Interfaces:**
- Consumes: `const.DEFAULT_SCAN_INTERVAL`, `const.FETCH_TIMEOUT` (Task 1).
- Produces:
  - `coordinator.CellarTrackerCoordinator(hass: HomeAssistant, entry: ConfigEntry, score_bands=DEFAULT_SCORE_BANDS)`
  - `coordinator.CellarTrackerConfigEntry` = `ConfigEntry[CellarTrackerCoordinator]` (type alias)
  - `coordinator.CellarTracker` — module-level name (patch target in tests)
  - `__init__.PLATFORMS = [Platform.SENSOR]`, `async_setup_entry(hass, entry) -> bool`, `async_unload_entry(hass, entry) -> bool`
  - `sensor.async_setup_entry(hass, entry, async_add_entities) -> None`
  - Fixtures `mock_client` (patched `CellarTracker` class; `mock_client.return_value.get_inventory` is the mock to configure) and `config_entry` (`MockConfigEntry`, title `Alice`, unique ID `alice`, data `{username: "Alice", password: "pw"}`, options `{scan_interval: 3600}`).

- [ ] **Step 1: Add fixtures to `tests/conftest.py`**

Replace the file with:

```python
"""Shared fixtures.

pytest-homeassistant-custom-component refuses to load anything from
custom_components/ unless `enable_custom_integrations` is requested, and its
own fixture is not autouse.
"""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cellar_tracker.const import DOMAIN
from tests.fixtures import SAMPLE_ROWS


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def mock_client():
    """Patch the CellarTracker class the coordinator instantiates.

    Configure behaviour through mock_client.return_value.get_inventory.
    """
    cls = MagicMock()
    cls.return_value.get_inventory.return_value = [dict(row) for row in SAMPLE_ROWS]
    with patch("custom_components.cellar_tracker.coordinator.CellarTracker", cls):
        yield cls


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Alice",
        unique_id="alice",
        data={CONF_USERNAME: "Alice", CONF_PASSWORD: "pw"},
        options={CONF_SCAN_INTERVAL: 3600},
    )
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_init.py`:

```python
"""Config entry setup, unload and registry continuity."""

from cellartracker.errors import CannotConnect
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.cellar_tracker.const import DOMAIN


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_entities(hass: HomeAssistant, mock_client, config_entry):
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.cellar_tracker_total_bottles").state == "5"
    assert hass.states.get("sensor.cellar_tracker_country_france") is not None
    assert hass.states.get("sensor.cellar_tracker_by_producer") is not None
    mock_client.assert_called_once_with("Alice", "pw")


async def test_friendly_names_are_unchanged(hass: HomeAssistant, mock_client, config_entry):
    await _setup(hass, config_entry)

    state = hass.states.get("sensor.cellar_tracker_total_bottles")
    assert state.attributes["friendly_name"] == "Cellar Tracker total bottles"


async def test_entities_belong_to_one_service_device(
    hass: HomeAssistant, mock_client, config_entry
):
    await _setup(hass, config_entry)

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, config_entry.entry_id)})
    assert device is not None
    assert device.name == "Cellar Tracker"
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    entity = er.async_get(hass).async_get("sensor.cellar_tracker_total_bottles")
    assert entity.device_id == device.id


async def test_cannot_connect_retries_setup(hass: HomeAssistant, mock_client, config_entry):
    mock_client.return_value.get_inventory.side_effect = CannotConnect

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload(hass: HomeAssistant, mock_client, config_entry):
    await _setup(hass, config_entry)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_yaml_era_entity_is_adopted_with_its_entity_id(
    hass: HomeAssistant, mock_client, config_entry
):
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor", DOMAIN, "cellar_tracker_total_bottles", suggested_object_id="my_bottles"
    )
    assert old.entity_id == "sensor.my_bottles"
    assert old.config_entry_id is None

    await _setup(hass, config_entry)

    adopted = registry.async_get("sensor.my_bottles")
    assert adopted is not None
    assert adopted.config_entry_id == config_entry.entry_id
    assert hass.states.get("sensor.my_bottles").state == "5"
    assert hass.states.get("sensor.cellar_tracker_total_bottles") is None


async def test_stale_yaml_era_entity_is_removed(hass: HomeAssistant, mock_client, config_entry):
    registry = er.async_get(hass)
    stale = registry.async_get_or_create("sensor", DOMAIN, "cellar_tracker_country_narnia")

    await _setup(hass, config_entry)

    assert registry.async_get(stale.entity_id) is None
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --with pytest-homeassistant-custom-component --with cellartracker --with pandas pytest tests/test_init.py -q`
Expected: FAIL — `AttributeError: ... does not have the attribute 'CellarTracker'` (the coordinator imports the module, not the class) or a missing `async_setup_entry`.

- [ ] **Step 4: Rewrite `coordinator.py`**

```python
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
```

- [ ] **Step 5: Rewrite `__init__.py`**

```python
"""Cellar Tracker integration.

Set up from a config entry. The YAML block is still accepted so existing
users can be imported (see async_setup); it no longer configures anything
by itself. See docs/superpowers/specs/2026-09-30-config-flow-design.md.
"""

from __future__ import annotations

import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MIN_SCAN_INTERVAL
from .coordinator import CellarTrackerConfigEntry, CellarTrackerCoordinator
from .migrate import async_cleanup_registry
from .naming import expected_unique_ids

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

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
    """Accept the legacy YAML block. Import is added in a later change."""
    return True


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
            "Skipping registry cleanup: the inventory came back empty or "
            "without recognised columns"
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CellarTrackerConfigEntry) -> bool:
    """Unload a config entry. The coordinator shuts itself down via async_on_unload."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

> Task 4 later replaces the docstring, the YAML `CONFIG_SCHEMA` and `async_setup` above with `cv.config_entry_only_config_schema(DOMAIN)`.

- [ ] **Step 6: Update `sensor.py`**

Replace the imports block (from `from homeassistant.components.sensor import (` down to `from .naming import SLICE_DIMENSIONS, unique_slugs`) with:

```python
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
```

Replace the `_Base` class with:

```python
class _Base(CoordinatorEntity[CellarTrackerCoordinator], SensorEntity):
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
```

Change the three name assignments:

- `CellarValueSensor.__init__`: `self._attr_name = f"Cellar Tracker {dimension} {value}"` → `self._attr_name = f"{dimension} {value}"`
- `CellarSliceSensor.__init__`: `self._attr_name = f"Cellar Tracker by {dimension}"` → `self._attr_name = f"by {dimension}"`
- In `SCALAR_SPECS`, drop the `"Cellar Tracker "` prefix from the four names: `"total bottles"`, `"total value"`, `"average value"`, `"average score"`.

Replace `async_setup_platform` at the end of the file with:

```python
async def async_setup_entry(
    hass: HomeAssistant,
    entry: CellarTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    async_add_entities(build_entities(entry.runtime_data))
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run --with pytest-homeassistant-custom-component --with cellartracker --with pandas pytest tests -q`
Expected: `43 passed`

- [ ] **Step 8: Lint, format, type-check**

Run: `uvx ruff check . && uvx ruff format . && uvx ty check`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add custom_components/cellar_tracker/coordinator.py custom_components/cellar_tracker/__init__.py custom_components/cellar_tracker/sensor.py tests/conftest.py tests/test_init.py
git commit -m "feat: set up from a config entry with a service device

Unique IDs are unchanged, so YAML-era registry entries are adopted
with their entity IDs, renames and areas intact.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Config flow — user, reauth, options

**Files:**
- Create: `custom_components/cellar_tracker/config_flow.py`
- Create: `custom_components/cellar_tracker/strings.json`
- Create: `custom_components/cellar_tracker/translations/en.json`
- Modify: `custom_components/cellar_tracker/manifest.json`
- Modify: `tests/conftest.py` (`mock_client` also patches the flow)
- Create: `tests/test_config_flow.py`
- Modify: `tests/test_init.py` (append the reauth-trigger test)

**Interfaces:**
- Consumes: `const.FETCH_TIMEOUT`, `const.DEFAULT_SCAN_INTERVAL`, `const.MIN_SCAN_INTERVAL` (Task 1); `mock_client`, `config_entry` fixtures (Task 2).
- Produces:
  - `config_flow.CellarTracker` — module-level name (patch target)
  - `config_flow._async_error_key(hass, username: str, password: str) -> str | None` — returns `None`, `"invalid_auth"`, `"cannot_connect"` or `"unknown"`
  - `config_flow.CellarTrackerConfigFlow` (steps `user`, `reauth`, `reauth_confirm`)
  - `config_flow.CellarTrackerOptionsFlow` (step `init`)

- [ ] **Step 1: Make `mock_client` patch the flow too**

In `tests/conftest.py`, replace the `mock_client` fixture with:

```python
@pytest.fixture
def mock_client():
    """Patch the CellarTracker class in both places it is instantiated.

    Configure behaviour through mock_client.return_value.get_inventory.
    """
    cls = MagicMock()
    cls.return_value.get_inventory.return_value = [dict(row) for row in SAMPLE_ROWS]
    with (
        patch("custom_components.cellar_tracker.coordinator.CellarTracker", cls),
        patch("custom_components.cellar_tracker.config_flow.CellarTracker", cls),
    ):
        yield cls
```

- [ ] **Step 2: Write the failing flow tests**

Create `tests/test_config_flow.py`:

```python
"""Config and options flow tests."""

import pytest
from cellartracker.errors import AuthenticationError, CannotConnect
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.cellar_tracker.const import DOMAIN


async def _start_user_flow(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_client):
    result = await _start_user_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "Alice", CONF_PASSWORD: "pw"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Alice"
    assert result["data"] == {CONF_USERNAME: "Alice", CONF_PASSWORD: "pw"}
    assert result["result"].unique_id == "alice"


async def test_user_flow_accepts_an_empty_cellar(hass: HomeAssistant, mock_client):
    mock_client.return_value.get_inventory.return_value = []

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "Alice", CONF_PASSWORD: "pw"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (AuthenticationError, "invalid_auth"),
        (CannotConnect, "cannot_connect"),
        (TimeoutError, "cannot_connect"),
        (RuntimeError, "unknown"),
    ],
)
async def test_user_flow_errors_then_recovers(
    hass: HomeAssistant, mock_client, side_effect, error
):
    mock_client.return_value.get_inventory.side_effect = side_effect

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "Alice", CONF_PASSWORD: "bad"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_client.return_value.get_inventory.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "Alice", CONF_PASSWORD: "pw"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_second_user_flow_is_rejected(hass: HomeAssistant, mock_client, config_entry):
    config_entry.add_to_hass(hass)

    result = await _start_user_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_reauth_updates_password(hass: HomeAssistant, mock_client, config_entry):
    await _setup(hass, config_entry)

    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-pw"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data == {CONF_USERNAME: "Alice", CONF_PASSWORD: "new-pw"}
    assert config_entry.unique_id == "alice"
    mock_client.assert_called_with("Alice", "new-pw")


async def test_reauth_wrong_password_shows_error(
    hass: HomeAssistant, mock_client, config_entry
):
    await _setup(hass, config_entry)
    mock_client.return_value.get_inventory.side_effect = AuthenticationError

    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "still-wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert config_entry.data[CONF_PASSWORD] == "pw"


async def test_options_flow_saves_interval_and_reloads(
    hass: HomeAssistant, mock_client, config_entry
):
    await _setup(hass, config_entry)
    assert mock_client.return_value.get_inventory.call_count == 1

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["step_id"] == "init"
    # Must differ from the current 3600: OptionsFlowWithReload only reloads
    # when the options actually change.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 600}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_SCAN_INTERVAL: 600}
    assert isinstance(config_entry.options[CONF_SCAN_INTERVAL], int)
    assert mock_client.return_value.get_inventory.call_count == 2
```

In `tests/test_init.py`, change the top imports

```python
from cellartracker.errors import CannotConnect
from homeassistant.config_entries import ConfigEntryState
```

to

```python
from cellartracker.errors import AuthenticationError, CannotConnect
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
```

and append:

```python
async def test_auth_failure_starts_reauth(hass: HomeAssistant, mock_client, config_entry):
    mock_client.return_value.get_inventory.side_effect = AuthenticationError

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --with pytest-homeassistant-custom-component --with cellartracker --with pandas pytest tests -q`
Expected: FAIL — `ModuleNotFoundError`/`AttributeError` for `custom_components.cellar_tracker.config_flow`.

- [ ] **Step 4: Create `config_flow.py`**

```python
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
            username = user_input[CONF_USERNAME]
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
```

- [ ] **Step 5: Create `strings.json` and `translations/en.json`**

Write this exact content to both `custom_components/cellar_tracker/strings.json` and `custom_components/cellar_tracker/translations/en.json`:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Connect to CellarTracker!",
        "description": "Sign in with your CellarTracker! account.",
        "data": {
          "username": "Username",
          "password": "Password"
        },
        "data_description": {
          "username": "The username you sign in with at cellartracker.com.",
          "password": "Your CellarTracker! password."
        }
      },
      "reauth_confirm": {
        "title": "Re-authenticate CellarTracker!",
        "description": "CellarTracker! rejected the password for {name}. Enter the current password.",
        "data": {
          "password": "Password"
        },
        "data_description": {
          "password": "Your CellarTracker! password."
        }
      }
    },
    "error": {
      "invalid_auth": "Invalid username or password.",
      "cannot_connect": "Could not reach CellarTracker!. Try again later.",
      "unknown": "Unexpected error. See the Home Assistant log for details."
    },
    "abort": {
      "reauth_successful": "Re-authentication was successful."
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "Cellar Tracker options",
        "data": {
          "scan_interval": "Update interval"
        },
        "data_description": {
          "scan_interval": "Seconds between inventory fetches. Minimum 30."
        }
      }
    }
  }
}
```

- [ ] **Step 6: Update `manifest.json`**

Replace the file with (keys in hassfest order: `domain`, `name`, then alphabetical):

```json
{
  "domain": "cellar_tracker",
  "name": "Cellar Tracker",
  "codeowners": [
    "@ahoernecke"
  ],
  "config_flow": true,
  "dependencies": [],
  "documentation": "https://github.com/ahoernecke/ha_cellar_tracker",
  "integration_type": "service",
  "iot_class": "cloud_polling",
  "requirements": [
    "cellartracker",
    "pandas"
  ],
  "single_config_entry": true,
  "version": "20260914"
}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run --with pytest-homeassistant-custom-component --with cellartracker --with pandas pytest tests -q`
Expected: `54 passed`

- [ ] **Step 8: Lint, format, type-check**

Run: `uvx ruff check . && uvx ruff format . && uvx ty check`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add custom_components/cellar_tracker/config_flow.py custom_components/cellar_tracker/strings.json custom_components/cellar_tracker/translations/en.json custom_components/cellar_tracker/manifest.json tests/conftest.py tests/test_config_flow.py tests/test_init.py
git commit -m "feat: add config flow with reauth and options

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Drop YAML configuration

YAML is no longer read (spec revision 2026-09-30: clean break, single existing install). A leftover block raises HA core's `config_entry_only` repair issue.

**Files:**
- Modify: `custom_components/cellar_tracker/__init__.py` (docstring, imports, `CONFIG_SCHEMA`, delete `async_setup`)
- Modify: `tests/test_init.py` (append one test, widen imports)

**Interfaces:**
- Consumes: `mock_client` fixture (Task 3 version, patches coordinator and config_flow).
- Produces: `__init__.CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)`; no `async_setup`. `const.DEFAULT_SCAN_INTERVAL`/`MIN_SCAN_INTERVAL` stay (used by `coordinator.py` and `config_flow.py`).

- [ ] **Step 1: Write the failing test**

In `tests/test_init.py`, add these imports at the top alongside the existing ones (let `uvx ruff check --fix tests/test_init.py` sort them):

```python
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
```

Append:

```python
async def test_yaml_block_is_rejected_with_repair_issue(hass: HomeAssistant, mock_client):
    yaml = {DOMAIN: {CONF_USERNAME: "Alice", CONF_PASSWORD: "pw"}}

    assert await async_setup_component(hass, DOMAIN, yaml)
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries(DOMAIN) == []
    mock_client.assert_not_called()
    issue = ir.async_get(hass).async_get_issue(HOMEASSISTANT_DOMAIN, f"config_entry_only_{DOMAIN}")
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pytest-homeassistant-custom-component --with cellartracker --with pandas pytest tests/test_init.py -q -k yaml_block`
Expected: FAIL on `assert issue is not None` (the current YAML schema accepts the block silently).

- [ ] **Step 3: Rewrite the top of `__init__.py`**

Replace everything from the start of `custom_components/cellar_tracker/__init__.py` down to and including the `async_setup` function (i.e. the docstring, imports, `_LOGGER`, `PLATFORMS`, the old `CONFIG_SCHEMA` and `async_setup`) with:

```python
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
```

Leave `async_setup_entry` and `async_unload_entry` exactly as they are.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --with pytest-homeassistant-custom-component --with cellartracker --with pandas pytest tests -q`
Expected: `55 passed`

- [ ] **Step 5: Lint, format, type-check**

Run: `uvx ruff check . && uvx ruff format custom_components/cellar_tracker/__init__.py tests/test_init.py && uvx ty check`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add custom_components/cellar_tracker/__init__.py tests/test_init.py
git commit -m "feat: drop YAML configuration in favour of the config flow

A leftover cellar_tracker: block now raises Home Assistant's
config_entry_only repair issue instead of configuring anything.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Documentation and version bump

**Files:**
- Modify: `README.md` (the `# Configuration:` section)
- Modify: `CLAUDE.md` (Development workflow, Architecture)
- Modify: `custom_components/cellar_tracker/manifest.json` (`version`)
- Modify: `custom_components/cellar_tracker/migrate.py` (module docstring)

**Interfaces:**
- Consumes: everything above. Produces: nothing code-level.

- [ ] **Step 1: README — replace the Configuration section**

In `README.md`, replace everything from the line `# Configuration:` up to (not including) the line `## Entities` with:

````markdown
# Configuration

Go to **Settings → Devices & services → Add integration**, search for **Cellar Tracker**, and sign in with your CellarTracker! username and password. The login is checked against CellarTracker! before the integration is added.

Only one CellarTracker! account can be added per Home Assistant instance.

## Options

Open the integration and choose **Configure** to change the update interval (in seconds, default 3600, minimum 30). The integration reloads with the new interval when you save.

## Changed password

If CellarTracker! stops accepting your password, Home Assistant shows a **Re-authenticate** prompt for the integration. Enter the new password there; your entities are kept.

## Upgrading from YAML

Earlier versions were configured with a `cellar_tracker:` block in `configuration.yaml`. Delete that block (and the `cellar_tracker_username`/`cellar_tracker_password` entries in `secrets.yaml` if nothing else uses them), restart Home Assistant, then add the integration from the UI as above. Existing entity IDs, renames and areas are kept, because the sensors' unique IDs have not changed. If the block is left in place, Home Assistant shows a repair notice and ignores it.

````

- [ ] **Step 2: CLAUDE.md — development workflow**

Replace the paragraph that begins "`aggregate.py`, `naming.py` and `migrate.py` are exercised by the `tests/` pytest suite." with:

```markdown
The whole integration is exercised by the `tests/` pytest suite, run on `pytest-homeassistant-custom-component`, which pins a matching Home Assistant and provides the `hass` fixture and `MockConfigEntry`. `tests/conftest.py` enables custom integrations for every test and provides `mock_client` (the patched `CellarTracker` class, used by both `coordinator.py` and `config_flow.py`) and `config_entry`. `pyproject.toml` sets `asyncio_mode = "auto"`; without it the async `hass` fixture is ignored. To try it against a real CellarTracker account you must still run it inside Home Assistant:
```

Replace the line "Config is YAML-only (no config flow). See README.md for the `cellar_tracker:` block; dashboard YAML lives in `docs/dashboard/`." with:

```markdown
Setup is through the UI config flow (`config_flow.py`). YAML is not supported: `CONFIG_SCHEMA` is `cv.config_entry_only_config_schema`, so a leftover `cellar_tracker:` block only raises Home Assistant's own repair issue. Dashboard YAML lives in `docs/dashboard/`.
```

- [ ] **Step 3: CLAUDE.md — architecture**

Replace the paragraph beginning "**Coordinator + platform split.**" with:

```markdown
**Coordinator + platform split.** `__init__.py` owns setup; `CellarTrackerCoordinator` (`coordinator.py`) owns fetching; `sensor.py` owns entities. They communicate only through `entry.runtime_data`, which holds the coordinator (typed as `CellarTrackerConfigEntry`). `async_setup_entry()` builds the coordinator from the entry (credentials in `entry.data`, `scan_interval` in `entry.options`) and awaits `async_config_entry_first_refresh()`, which raises `ConfigEntryNotReady` (HA retries with backoff) or `ConfigEntryAuthFailed` (HA starts reauth). It then runs registry cleanup only when the fetched data looks trustworthy, and forwards the sensor platform, so `sensor.async_setup_entry` can assume data is already populated. The coordinator shuts itself down through the entry; never call `async_register_shutdown()`, which raises with a config entry. Anything that changes the shape of the data must be changed in `aggregate.py`, `naming.py`, and `sensor.py` together.

**Config flow.** `config_flow.py` has `user`, `reauth_confirm` and an options `init` step. All of them validate by fetching the inventory (`_async_error_key`), mapping `AuthenticationError` → `invalid_auth`, `CannotConnect`/`TimeoutError` → `cannot_connect`, anything else → `unknown`. The entry unique ID is `username.lower()`. `manifest.json` sets `single_config_entry`, so HA rejects a second setup before the flow runs. `strings.json` and `translations/en.json` must stay identical; custom integrations load only the latter, and `[%key:...%]` references do not resolve in them.
```

In the "**Entity naming is load-bearing.**" paragraph, append this sentence at the end:

```markdown
Entities set `has_entity_name` and belong to one service device named "Cellar Tracker", so `_attr_name` omits that prefix ("total bottles") and HA adds it back: entity IDs and friendly names are the same as before the config flow. Do not rename the device in code; that changes every friendly name.
```

- [ ] **Step 4: Bump the manifest version**

In `custom_components/cellar_tracker/manifest.json`, change `"version": "20260914"` to `"version": "20260930"`.

- [ ] **Step 5: Update `migrate.py`'s docstring**

Replace the module docstring of `custom_components/cellar_tracker/migrate.py` with:

```python
"""Remove entities the current model no longer provides.

Filters on platform, not config entry: entities registered by the YAML-era
setup have no config entry until the new entry adopts them, and orphaned
ones never will be. Left alone, Home Assistant writes `unavailable` for each
of them at every start, forever -- the 30-day orphan purge only applies to
entries already marked deleted. Correct only because the manifest allows a
single config entry.
"""
```

- [ ] **Step 6: Full verification**

Run: `uvx ruff check . && uvx ruff format --check $(git diff --name-only 13e56c5 -- '*.py') && uvx ty check && uv run --with pytest-homeassistant-custom-component --with cellartracker --with pandas pytest tests -q`
Expected: no lint or type errors; `55 passed`.

- [ ] **Step 7: Commit**

```bash
git add README.md CLAUDE.md custom_components/cellar_tracker/manifest.json custom_components/cellar_tracker/migrate.py
git commit -m "docs: document UI setup and YAML migration

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
