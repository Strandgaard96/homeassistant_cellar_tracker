# Config flow for Cellar Tracker

Date: 2026-09-30
Status: approved. Revised after independent review against HA 2026.2.3
source, and again on 2026-09-30 to drop the YAML import in favour of a clean
break (single existing install).

## Goal

Replace YAML-only setup with a UI config flow, as the first step toward
listing the integration in the HACS default repository and, later, a
Home Assistant core submission. Existing YAML users must upgrade without
losing entity IDs, renames, area assignments, history or dashboards.

## Decisions

| Question | Decision |
|---|---|
| Existing YAML users | Clean break (revised 2026-09-30). YAML is no longer read; a leftover block triggers HA's built-in `config_entry_only` repair issue. The user removes the YAML and adds the integration in the UI. Entity IDs survive because unique IDs are unchanged (see Section 3). Chosen over auto-import because the only existing install is the author's own. |
| Accounts per HA instance | One. `single_config_entry: true`. Entity unique IDs are unchanged. |
| Scope | User step, reauth, options flow (`scan_interval`), a service device with `has_entity_name`, translations. |
| Setup style | Modern config-entry setup: `entry.runtime_data`, `async_config_entry_first_refresh()`, `async_forward_entry_setups`. |

Out of scope, for a follow-up spec: GitHub Actions for `hassfest` and
`hacs/action`, brand icons in `home-assistant/brands`, correcting
`codeowners`/`documentation`/`issue_tracker` (they still point at the
upstream `ahoernecke` repo), diagnostics, a reconfigure step, and wrapping
the `cellartracker` library (no request timeout; credentials sent as GET
query parameters).

## Library facts this design relies on

`cellartracker` 1.1.1 (MIT, PyPI) raises two distinct exceptions from
`cellartracker.errors`:

- `AuthenticationError` -- the response body contained CellarTracker's
  "not logged in" marker.
- `CannotConnect` -- any `requests.exceptions.RequestException`.

`requests.get` is called without a timeout, so a hung connection can block
an executor thread indefinitely.

## Section 1: Setup lifecycle

### YAML

`async_setup` is removed. `CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)`:
if a `cellar_tracker:` block is still present, HA logs an error and raises
the core ERROR issue `config_entry_only_cellar_tracker` (domain
`homeassistant`, text supplied by core). Nothing is imported.

### `async_setup_entry(hass, entry)`

1. Build `CellarTrackerCoordinator(hass, entry)`. It reads the username and
   password from `entry.data` and `scan_interval` from `entry.options`,
   falling back to `DEFAULT_SCAN_INTERVAL` (3600). The coordinator is
   constructed with `config_entry=entry`.
2. `await coordinator.async_config_entry_first_refresh()`. On failure this
   raises `ConfigEntryNotReady` (retried by HA with backoff) or
   `ConfigEntryAuthFailed` (starts reauth). Today's `return False`
   leaves the integration dead until restart, so this is an improvement.
3. `entry.runtime_data = coordinator`. `hass.data[DOMAIN]` is no longer
   used.
4. Registry cleanup: same trust guard as today
   (`data.total_bottles and data.low`), same `async_cleanup_registry`, run
   before platforms are forwarded.
5. `await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])`.

`async_register_shutdown()` must be removed: with a config entry it raises
`RuntimeError`. The coordinator registers `async_shutdown` via
`config_entry.async_on_unload` in its own `__init__`.

### `async_unload_entry(hass, entry)`

`return await hass.config_entries.async_unload_platforms(entry, ["sensor"])`.

### Coordinator error mapping

`_async_update_data` wraps the executor job in `asyncio.timeout(60)`:

| Raised | Becomes |
|---|---|
| `AuthenticationError` | `ConfigEntryAuthFailed` |
| `CannotConnect` | `UpdateFailed` |
| any other `Exception` | `UpdateFailed` |

`TimeoutError` needs no clause: the coordinator base class already turns it
into a failed update. `except AuthenticationError` must come before the
generic `except Exception`, as a separate clause, so the auth error is not
swallowed.

The timeout stops the await, not the thread: a stuck `requests` call keeps
its executor thread until the socket gives up. Acceptable at an hourly
poll; the real fix belongs in the library.

`ever_succeeded` and the stale-tolerant `available` are unchanged.

## Section 2: Flow steps and errors

`config_flow.py` holds `CellarTrackerConfigFlow(ConfigFlow, domain=DOMAIN)`
with `VERSION = 1`, `CellarTrackerOptionsFlow(OptionsFlowWithReload)`, and a
shared helper:

```python
async def _async_validate(hass, username: str, password: str) -> None:
    """Raise AuthenticationError, CannotConnect or TimeoutError on failure."""
```

It runs `CellarTracker(username, password).get_inventory()` in the executor
under `asyncio.timeout(60)`. An empty inventory is a valid login and passes.

Each step catches those exceptions and maps them to a form error key:

| Exception | `errors["base"]` |
|---|---|
| `AuthenticationError` | `invalid_auth` |
| `CannotConnect`, `TimeoutError` | `cannot_connect` |
| other `Exception` | `unknown`, plus `_LOGGER.exception` |

| Step | Form | Behaviour |
|---|---|---|
| `user` | `username`, `password` (password `TextSelector` with `type=password`) | Validate. `async_set_unique_id(username.lower())`, create entry titled with the username, `data={username, password}`. |
| `reauth` | none | Go straight to `reauth_confirm`. `_get_reauth_entry()` reads the entry from the flow context, so nothing needs storing. |
| `reauth_confirm` | `password` only; username shown via the auto-injected `{name}` placeholder (the entry title, which is the username) | Validate against `self._get_reauth_entry().data[username]`. On success, `async_update_reload_and_abort(self._get_reauth_entry(), data_updates={password})`, which aborts with `reauth_successful`. The unique ID cannot change because the username is not editable. |
| options `init` | `scan_interval` as a `NumberSelector` (box mode, seconds, min 30, step 1), prefilled from options or 3600 | `async_create_entry(data=user_input)`. `OptionsFlowWithReload` reloads the entry, so there is no update listener. |

`async_get_options_flow` is a `@staticmethod` returning
`CellarTrackerOptionsFlow()`.

`single_config_entry: true` makes HA abort a second user flow with
`single_instance_allowed` before the handler is even constructed
(`config_entries.py` `async_init`), so no step calls
`_abort_if_unique_id_configured()`: it would be unreachable. Reauth is
exempt from that guard. The user step still sets the unique ID so a core
port needs no unique-ID migration.

## Section 3: Entities, device and registry continuity

### Device

All entities share one `DeviceInfo`:

```python
DeviceInfo(
    identifiers={(DOMAIN, entry.entry_id)},
    name="Cellar Tracker",
    manufacturer="CellarTracker!",
    entry_type=DeviceEntryType.SERVICE,
    configuration_url="https://www.cellartracker.com",
)
```

### Naming

`_Base` sets `_attr_has_entity_name = True` and `_attr_device_info`, built
from `coordinator.config_entry.entry_id`, so `build_entities(coordinator)`
keeps its signature.
Entity names drop their `"Cellar Tracker "` prefix:

| Class | Old `_attr_name` | New `_attr_name` |
|---|---|---|
| `CellarValueSensor` | `Cellar Tracker {dimension} {value}` | `{dimension} {value}` |
| `CellarSliceSensor` | `Cellar Tracker by {dimension}` | `by {dimension}` |
| `CellarScalarSensor` | `Cellar Tracker total bottles` etc. | `total bottles` etc. (`SCALAR_SPECS` updated) |

With `has_entity_name`, HA prefixes the device name, so a fresh install still
gets `sensor.cellar_tracker_country_france` and the same friendly names.
The value is part of the name, so names stay as `_attr_name` rather than
`translation_key`.

The lowercase-first names deliberately deviate from HA's guidance that
entity names start with a capital letter, to keep friendly names identical
to today's. The slug is unaffected. A core reviewer would flag this;
revisit for the core port. If a user renames the device, every friendly
name changes with it; entity IDs do not.

### Unique IDs and adoption

Unique IDs are unchanged. `EntityRegistry.async_get_or_create` (HA 2026.2.3)
finds an existing `(sensor, cellar_tracker, unique_id)` entry and calls
`_async_update_entity(..., config_entry_id=...)`, so YAML-era entities are
adopted by the new config entry with their `entity_id`, name overrides,
area and history intact.

### Registry cleanup

`async_cleanup_registry` keeps filtering on `entry.platform == DOMAIN`. That
is correct with a single config entry, and it still matches YAML-era
entries whose `config_entry_id` is `None` and have not yet been adopted.
It runs before platform forwarding, as today.

### Platform

`async_setup_platform` and the `discovery` import are removed.
`sensor.async_setup_entry(hass, entry, async_add_entities)` reads
`entry.runtime_data` and calls `async_add_entities(build_entities(coordinator))`.

## Section 4: Files, translations, testing

### New files

- `custom_components/cellar_tracker/config_flow.py`
- `custom_components/cellar_tracker/strings.json`
- `custom_components/cellar_tracker/translations/en.json` (a copy of
  `strings.json`: custom integrations load `translations/`, not `strings.json`)

Translation keys:

- `config.step.user`, `config.step.reauth_confirm` (titles, field labels,
  `data_description`)
- `config.error.invalid_auth`, `cannot_connect`, `unknown`
- `config.abort.reauth_successful`
- `options.step.init` (`scan_interval` label and description)

The `config_entry_only` and `single_instance_allowed` texts come from HA
core's `homeassistant` domain and need no string of ours.

`translations/en.json` must be full, flat text. `[%key:...%]` references
are resolved only by core's build step and render literally in a custom
integration.

### Changed files

- `manifest.json`: add `"config_flow": true`, `"single_config_entry": true`,
  `"integration_type": "service"`, `"iot_class": "cloud_polling"`; bump
  `version`.
- `__init__.py`, `coordinator.py`, `sensor.py`: per Sections 1-3.
- `const.py`: move `DEFAULT_SCAN_INTERVAL` and `MIN_SCAN_INTERVAL` here so
  `__init__.py` and `config_flow.py` share them.
- `README.md`: UI setup, options, and a note to delete the old YAML block.
- `CLAUDE.md`: rewrite the "Coordinator + platform split" paragraph, remove
  "Config is YAML-only", update the test command.

### Testing

Add `pytest-homeassistant-custom-component` (provides the `hass` fixture,
`MockConfigEntry`, and pins a compatible HA). The test command becomes:

```bash
uv run --with pytest-homeassistant-custom-component --with cellartracker --with pandas pytest tests -q
```

`pyproject.toml` gets `asyncio_mode = "auto"` under
`[tool.pytest.ini_options]`: the plugin's `hass` fixture is a plain
`@pytest.fixture` over an async function, which pytest-asyncio's default
strict mode ignores. `tests/conftest.py` defines an autouse fixture that
requests `enable_custom_integrations` (the plugin's version is not autouse).
Tests drive setup through `MockConfigEntry.add_to_hass` plus
`hass.config_entries.async_setup(entry.entry_id)`, never by calling the
coordinator directly: `async_config_entry_first_refresh` raises
`ConfigEntryError` unless the entry is in `SETUP_IN_PROGRESS`. `CellarTracker` is patched in
`custom_components.cellar_tracker.config_flow` and `.coordinator`.

New `tests/test_config_flow.py`:

- user: success creates an entry with the expected data and unique ID
- user: `invalid_auth`, `cannot_connect`, `unknown` show the error, then
  recover on retry
- user: second flow aborts with `single_instance_allowed`
- reauth: success updates the password and aborts `reauth_successful`
- reauth: wrong password shows `invalid_auth`
- options: saving a `scan_interval` different from the current one updates
  options and reloads the entry (`OptionsFlowWithReload` reloads only on a
  change)

New `tests/test_init.py`:

- setup: success loads the entry and creates the expected entities
- setup: `AuthenticationError` on first refresh leaves the entry in
  `SETUP_ERROR` with a reauth flow in progress
- setup: `CannotConnect` on first refresh leaves the entry in `SETUP_RETRY`
- unload: entry unloads cleanly
- registry continuity: an entity pre-registered with `config_entry=None` and
  a custom `entity_id` keeps that `entity_id` and gains the entry's
  `config_entry_id` after setup

Existing tests stay; any assertion on the old `"Cellar Tracker ..."` names
is updated.

## Risks

- `pytest-homeassistant-custom-component` pins a HA version; the existing
  tests that use `homeassistant` directly must still pass against it.
- `hacs.json` sets `"homeassistant": "2026.2.0"`. `OptionsFlowWithReload`,
  `_get_reauth_entry` and `single_config_entry` all predate that.
