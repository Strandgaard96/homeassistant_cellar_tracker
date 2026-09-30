# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant **custom integration** (HACS-distributed) that pulls a CellarTracker wine inventory and exposes it as sensors. It is not a standalone app: there is no build step and no CI. Of the aggregation and naming logic, only `aggregate.py`, `const.py` and `naming.py` are plain Python with no Home Assistant import; `migrate.py` does import `homeassistant.core` and `homeassistant.helpers.entity_registry`. All of it is covered by a `pytest` suite under `tests/`. The integration itself is under `custom_components/cellar_tracker/`.

## Commands

Lint and type-check via `uv` (no project venv needed, nothing to install):

```bash
uvx ruff check .          # lint
uvx ruff check . --fix    # lint + autofix
uvx ruff format .         # format
uvx ty check              # type-check
uv run --with pytest-homeassistant-custom-component --with cellartracker --with pandas pytest tests -q   # tests
```

All of these must come back clean before committing. Config lives in `pyproject.toml`, which is dev tooling only and is never shipped to a user's HA instance.

## Development workflow

The whole integration is exercised by the `tests/` pytest suite, run on `pytest-homeassistant-custom-component`, which pins a matching Home Assistant and provides the `hass` fixture and `MockConfigEntry`. `tests/conftest.py` enables custom integrations for every test and provides `mock_client` (the patched `CellarTracker` class, used by both `coordinator.py` and `config_flow.py`) and `config_entry`. `pyproject.toml` sets `asyncio_mode = "auto"`; without it the async `hass` fixture is ignored. To try it against a real CellarTracker account you must still run it inside Home Assistant:

```bash
# Deploy into a HA instance
cp -r custom_components/cellar_tracker /path/to/homeassistant/config/custom_components/
# then restart Home Assistant
```

Debug output (all `_LOGGER.debug`) requires enabling the logger in HA's `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.cellar_tracker: debug
```

Setup is through the UI config flow (`config_flow.py`). YAML is not supported: `CONFIG_SCHEMA` is `cv.config_entry_only_config_schema`, so a leftover `cellar_tracker:` block only raises Home Assistant's own repair issue. Dashboard YAML lives in `docs/dashboard/`.

## Architecture

**Coordinator + platform split.** `__init__.py` owns setup; `CellarTrackerCoordinator` (`coordinator.py`) owns fetching; `sensor.py` owns entities. They communicate only through `entry.runtime_data`, which holds the coordinator (typed as `CellarTrackerConfigEntry`). `async_setup_entry()` builds the coordinator from the entry (credentials in `entry.data`, `scan_interval` in `entry.options`) and awaits `async_config_entry_first_refresh()`, which raises `ConfigEntryNotReady` (HA retries with backoff) or `ConfigEntryAuthFailed` (HA starts reauth). It then runs registry cleanup only when the fetched data looks trustworthy, and forwards the sensor platform, so `sensor.async_setup_entry` can assume data is already populated. The coordinator shuts itself down through the entry; never call `async_register_shutdown()`, which raises with a config entry. Anything that changes the shape of the data must be changed in `aggregate.py`, `naming.py`, and `sensor.py` together.

**Config flow.** `config_flow.py` has `user`, `reauth_confirm` and an options `init` step. The `user` and `reauth_confirm` steps validate by fetching the inventory (`_async_error_key`), mapping `AuthenticationError` → `invalid_auth`, `CannotConnect`/`TimeoutError` → `cannot_connect`, anything else → `unknown`. The options `init` step stores only the int-coerced `scan_interval`; the entry then reloads via `OptionsFlowWithReload`. The entry unique ID is `username.lower()`. `manifest.json` sets `single_config_entry`, so HA rejects a second setup before the flow runs. `strings.json` and `translations/en.json` must stay identical; custom integrations load only the latter, and `[%key:...%]` references do not resolve in them.

**`CellarData` (`aggregate.py`) is the data contract.** `aggregate()` fetches the inventory, loads it into a pandas DataFrame, and produces a `CellarData` with: `low`, a dict of six low-cardinality dimensions (`country`, `type`, `size`, `category`, `location`, `color`) each mapping to a list of `GroupItem(name, count, value_avg, score_avg)`; `tails`, the same shape for nine long-tail/slice dimensions (`producer`, `store`, `appellation`, `varietal`, `mastervarietal`, `vintage`, `subregion`, `region`, `score_band`); and four scalars, `total_bottles`, `total_value`, `average_value`, `average_score`. `build_entities()` (`sensor.py`) walks `low` to build one `CellarValueSensor` per value, `SLICE_DIMENSIONS` to build one `CellarSliceSensor` per long-tail dimension, and the scalar specs to build four `CellarScalarSensor`s (count is data-dependent: one entity per low-cardinality value, 9 slice, 4 scalar). Adding a new low-cardinality or slice dimension automatically fans out into new entities; nothing here is a dict keyed by an open-ended shape any more.

**Entities are created once, at setup.** The set of sensors is frozen from the first fetch. A new country or producer appearing in CellarTracker later produces no new entity until Home Assistant restarts. `async_cleanup_registry` (`migrate.py`) removes any registry entry not in `expected_unique_ids(coordinator.data)`, so entities orphaned by a model or naming change (including the old sensor model) disappear automatically on the next start rather than lingering as unavailable.

**One coordinator, not two throttles.** `CellarTrackerCoordinator` (`coordinator.py`) owns fetching on `scan_interval`; entities are `CoordinatorEntity` with `should_poll = False`. The previous design applied `Throttle` to both the hub and every entity, and because `Throttle` only stamps its timestamp on success, a failing fetch was retried by every entity on every poll.

**Availability is deliberately stale-tolerant.** `CoordinatorEntity.available` defaults to `coordinator.last_update_success`, which blanks every entity after one failed refresh. `_Base.available` overrides it to `coordinator.ever_succeeded`, so a CellarTracker outage shows yesterday's inventory instead of nothing.

**Entity naming is load-bearing.** `unique_id`s are built as `{DOMAIN}_{dimension}_{slug}` for per-value sensors, `{DOMAIN}_by_{dimension}` for slice sensors, and `{DOMAIN}_{key}` for scalars (`naming.py`); HA slugifies `_attr_name` into the `entity_id`. `unique_slugs()` disambiguates values that would otherwise collide once slugified (e.g. `Domaine-Leroy` vs `Domaine Leroy`), and the resulting IDs no longer carry a `sub_type` attribute or a wildcard-matchable long tail — the README's dashboard cards select long-tail dimensions by exact entity ID and read the `items` attribute instead. Entities set `has_entity_name` and belong to one service device named "Cellar Tracker", so `_attr_name` omits that prefix ("total bottles") and HA adds it back: entity IDs and friendly names are the same as before the config flow. Do not rename the device in code; that changes every friendly name.

**Monetary values are native numbers, unit read from the data.** `total_value` gets `device_class: monetary`, `state_class: total` (measurement is invalid for monetary — HA logs a warning on every install if used), and a `native_unit_of_measurement` set to `coordinator.data.currency`, not hardcoded. `average_value` gets the same currency unit but no `device_class`, since an average is not a total.

**Quirks to preserve unless deliberately changing them:** vintage `"1001"` is remapped to `"NV"` (non-vintage) during aggregation; `Valuation` and `CT` (the score column) are coerced with `pd.to_numeric(..., errors="coerce")`, so a junk cell becomes NaN instead of killing the whole update.

## Dependencies

`manifest.json` `requirements` declares `cellartracker` and `pandas`. pandas is **not** part of Home Assistant core, so it must stay declared; it was previously omitted and the integration silently relied on some other component having pulled it in. Any new third-party import needs a matching `requirements` entry.

`manifest.json` `version` is a bare date string (`YYYYMMDD`); bump it on each release.
