# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant **custom integration** (HACS-distributed) that pulls a CellarTracker wine inventory and exposes it as sensors. It is not a standalone app: there is no build step, no test suite, and no CI. The entire integration is two files under `custom_components/cellar_tracker/`.

## Commands

Lint and type-check via `uv` (no project venv needed, nothing to install):

```bash
uvx ruff check .          # lint
uvx ruff check . --fix    # lint + autofix
uvx ty check              # type-check
```

Both must come back clean before committing. Config lives in `pyproject.toml`, which is dev tooling only and is never shipped to a user's HA instance.

`uvx ruff format .` is configured but has **not** been run on the existing code: `__init__.py` uses 3-space indents throughout, so formatting it rewrites the whole file and destroys `git blame`. Leave that decision to a deliberate, standalone commit.

## Development workflow

There is no test harness. To exercise changes you must run them inside Home Assistant:

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

Config is YAML-only (no config flow). See README.md for the `cellar_tracker:` block and the Flex Table Card dashboard snippets.

## Architecture

**Hub + platform split.** `__init__.py` owns data fetching; `sensor.py` owns entities. They communicate only through `hass.data[DOMAIN]`, which holds the single `WineCellarData` instance. `setup()` builds that object, calls `.update()` once synchronously, then `discovery.load_platform(...)` — so `sensor.setup_platform` can assume data is already populated. Anything that changes the shape of the data dict must be changed in both files.

**The data dict shape is the contract.** `WineCellarData._update()` fetches the inventory, loads it into a pandas DataFrame, and for each of eight group-by dimensions (`Varietal`, `Country`, `Vintage`, `Producer`, `Type`, `Location`, `Appellation`, `StoreName`) produces `data[group][value] = {count, value_total, value_avg, "%", sub_type}`. It then adds three scalars: `total_bottles`, `total_value`, `average_value`. `setup_platform` walks that dict and branches on `isinstance(value, dict)` — nested dicts become one sensor per group value, scalars become a single sensor. Adding a scalar key is safe; adding a nested key automatically fans out into new entities.

**Entities are created once, at setup.** The set of sensors is frozen from the first fetch. A new country or producer appearing in CellarTracker later produces no new entity until Home Assistant restarts.

**Double throttling.** The scan interval is applied twice with the same `timedelta`: once on `WineCellarData.update` (`__init__.py`) and once on each `WineCellarSensor.update` (`sensor.py`). Every sensor's update calls the hub's update, so the hub throttle is what actually collapses N entity polls into one HTTP fetch. Changing one throttle without the other will either spam CellarTracker or stall updates. Minimum interval is clamped to 30s in `setup()`.

**Entity naming is load-bearing.** `WineCellarSensor.name` returns a dotted string like `cellar_tracker.country.france`; HA slugifies that into `sensor.cellar_tracker_country_france`. The README's dashboard cards select entities by wildcard prefix (`sensor.cellar_tracker_country*`), so changing the naming scheme silently breaks every user's dashboard. `_slug` is built by lowercasing the group value and collapsing non-alphanumerics to `-`.

**Value sensors are strings, not numbers.** Any `sensor_type` matching `.+_value` is rendered as `f"{currency}{round(state,2)}"` with `unit_of_measurement` set to `None`. These entities have no `device_class` or `state_class`, so they are excluded from statistics and history graphs by design of the current code.

**Quirks to preserve unless deliberately changing them:** vintage `"1001"` is remapped to `"NV"` (non-vintage) during aggregation; `Price` and `Valuation` are coerced with `pd.to_numeric` and will raise on non-numeric cells rather than coercing to NaN.

## Dependencies

`manifest.json` `requirements` declares `cellartracker` and `pandas`. pandas is **not** part of Home Assistant core, so it must stay declared; it was previously omitted and the integration silently relied on some other component having pulled it in. Any new third-party import needs a matching `requirements` entry.

`manifest.json` `version` is a bare date string and has not been bumped for the current changes — do that as part of a release.
