# Cellar Tracker — sensor model and dashboard redesign

Date: 2026-09-14
Status: approved for planning

## Goal

Make the integration drive a dashboard whose job is **"what do I own, sliced every way"** — exploration and browsing, not drink decisions. Beauty and maintainability are the two acceptance criteria, in that order of visibility and reverse order of priority: nothing ships that adds a dependency we cannot expect to survive two years.

## Evidence

Every number below was measured against the live account on 2026-09-14, not assumed.

**Inventory: 1751 rows, 71 columns, one row per bottle.** 433 distinct `iWine`.

Available slice dimensions and their cardinality:

| Used today | | Available, unused | |
|---|---|---|---|
| `Country` | 8 | `Region` | 25 |
| `Vintage` | 34 | `SubRegion` | 26 |
| `Producer` | 184 | `Color` | 3 |
| `Varietal` | 39 | `Category` | 4 |
| `Type` | 9 | `Size` | 6 |
| `Appellation` | 64 | `MasterVarietal` | 38 |
| `Location` | 4 | `Designation` | 124 |
| `StoreName` | 67 | `Vineyard` | 118 |
| | | `Locale` | 69 |

The integration groups on 8 of 17 available dimensions.

**Scores live in `Inventory`, not `ProReview`.**

- `CT` (CellarTracker community score): **98% filled**, n=1722, min 80.0, max 100.0, mean 92.74
- `CNotes` (community note count): 100% filled
- Per-critic columns are unusable for this cellar: `WA` 0%, `WS` 0%, `IWC` 0%, `BH` 0%, `GV` 0%, `JG` 21%, `MFW` 11%, `CW` 2%

`CT` distribution is heavily clustered:

| Band | Bottles |
|---|---|
| <85 | 7 |
| 85–89.9 | 52 |
| 90–92.9 | **899** |
| 93–94.9 | 638 |
| 95+ | 126 |

51% of the cellar falls in a single 3-point band. Fixed wide bands are therefore a poor *visualisation*; the distribution chart uses 1-point bins across 80–100. Bands remain useful as a *slice*, and are configurable.

**Tables that do not work for this account:**

- `ProReview` → **0 rows**
- `Notes` → 48 rows against 1751 bottles; too sparse to slice
- `Consumed` → 2601 rows, **column-shifted and unusable**. Observed: `ConsumedQuarter` containing wine names (`Castell'in Villa Chianti Classico Riserva`), `ExchangeRate` containing `Forster Pechstein`. Free-text note fields carry embedded tabs/newlines that break TSV row alignment. `Inventory`, `Notes`, `List` and `Availability` all parse cleanly.

**Consequence: the entire dashboard is served by the single `get_inventory()` call that already exists.** No new HTTP fetches, no new failure modes, no new credentials surface.

**Currency:** `Currency` is a single value (`DKK`) with `ExchangeRate` of 1 across all rows.

## Problems in the current design

1. **One entity per group value.** 8 dimensions × their cardinality ≈ 400+ entities today, and adding the 9 unused dimensions would push past 1000. The registry becomes unusable and dashboards must wildcard-match entity IDs by hand.
2. **Entities are frozen at setup.** `setup_platform` walks the first fetch and creates the entity set once. A new producer never appears until Home Assistant restarts.
3. **Value sensors are strings.** `state` returns `f"{currency}{round(v,2)}"` with `unit_of_measurement: None`. No `device_class`, no `state_class` — so no history, no statistics, no graphs. Given a single-currency cellar, the string formatting buys nothing and costs everything.
4. **The dashboard needs `auto-entities` only because of (1) and (2).** That card last released 2025-05-28 and its default branch last moved 2025-08-21. (Its 168 `open_issues_count` bundles issues and PRs — see Dependencies.)

## Revision note (2026-09-14, post-review)

The first draft of this spec was reviewed and found unsafe to implement. Three claims in it were wrong against Home Assistant's actual behaviour, and one whole dashboard view had no implementation path. Everything from here down is the corrected design; the Evidence section above survived review unchanged.

What changed, and why:

| Was | Problem | Now |
|---|---|---|
| 15 slice entities, all dimensions | Entities inert outside the one dashboard; no automations, no voice, no history | Hybrid: 34 per-value sensors for low-cardinality dimensions, 9 slice entities for long tails |
| `monetary` + `measurement` | Invalid pairing. `sensor/const.py:844` maps `MONETARY` to `{TOTAL}` only; logs a warning per entity | `monetary` + `total` for totals; no device_class for averages |
| `_unrecorded_attributes` as DB hygiene | Actually load-bearing: `recorder/db_schema.py:90` caps attributes at 16384 bytes and stores `{}` for the whole entity when exceeded | Kept, with a stated payload budget and a test |
| Sankey Country→Region→Producer | Impossible. sankey-chart nodes are one-entity-one-scalar with no array expansion, and links need joint counts this model never produces | View deferred pending a spike |
| Bare `Entity` + double `Throttle` | `state_class` is only emitted by `SensorEntity`; failing fetches retry once per entity per poll | `SensorEntity` + `DataUpdateCoordinator` |
| No migration | ~400 old entities pin `unavailable` in the registry forever | Explicit registry cleanup at setup |

## Architecture

### Entity model: hybrid, split by cardinality

The first draft collapsed every dimension into a list attribute. That is wrong for low-cardinality dimensions, where a plain numeric sensor is strictly more useful: it works in `numeric_state` triggers, in templates without `selectattr` gymnastics, in voice assistants, in the entity picker, and it produces real long-term statistics.

**Per-value sensors — low cardinality (34 entities).** One sensor per distinct value, state = bottle count.

| Dimension | Values |
|---|---|
| `Country` | 8 |
| `Type` | 9 |
| `Size` | 6 |
| `Category` | 4 |
| `Location` | 4 |
| `Color` | 3 |

```
sensor.cellar_tracker_country_france     state: 612   bottles
sensor.cellar_tracker_color_red          state: 1204  bottles
```

`state_class: measurement`, `unit_of_measurement: bottles`, no `device_class`. Attributes carry `pct`, `value_total`, `value_avg`, `score_avg` — all scalars, all tiny.

These are the only entities whose set can change without a restart being acceptable, and their cardinality is stable enough that it rarely will. A genuinely new country triggers a registry addition on the next HA restart; a new *bottle* in an existing country does not.

**Slice entities — long tails (9 entities).** State = count of distinct values; breakdown in an `items` list attribute.

| Entity | Values |
|---|---|
| `sensor.cellar_tracker_by_producer` | 184 |
| `sensor.cellar_tracker_by_store` | 67 |
| `sensor.cellar_tracker_by_appellation` | 64 |
| `sensor.cellar_tracker_by_varietal` | 39 |
| `sensor.cellar_tracker_by_mastervarietal` | 38 |
| `sensor.cellar_tracker_by_vintage` | 34 |
| `sensor.cellar_tracker_by_subregion` | 26 |
| `sensor.cellar_tracker_by_region` | 25 |
| `sensor.cellar_tracker_by_score_band` | 6 |

`state_class: measurement`, no unit, no device_class. The state is a count of distinct values — honestly not very interesting, but numeric so the frontend treats it as such rather than rendering a timeline strip.

**These entities are for the Explore tables and little else.** Templating against them requires `state_attr('sensor.cellar_tracker_by_producer','items') | selectattr('name','eq','X') | map(attribute='count') | first`. That is the accepted cost of not having 184 entities. It is stated here rather than discovered later.

`Designation` (124), `Vineyard` (118) and `Locale` (69) remain excluded: long tails of one or two bottles, largely redundant with `Producer` and `Appellation`.

Total: 34 + 9 + 4 scalars = **47 entities**, replacing 400+.

**Score bands** (configurable via `CONFIG_SCHEMA`; defaults chosen against the measured distribution, which puts 51% of the cellar in a single 3-point range):

`<90` · `90–91.9` · `92–92.9` · `93–93.9` · `94–94.9` · `95+`

### `items` schema

```yaml
items:
  - name: Château Example
    count: 12
    value_avg: 673.7
    score_avg: 93.1
```

Sorted by `count` descending. `pct` and `value_total` are **derived, not stored** — `pct = count / total_bottles`, `value_total = count * value_avg` — which cuts payload roughly 35%. `score_avg` is omitted when no row in the group has a parseable `CT`.

All numbers are cast to native Python `int`/`float` when built. This is not cosmetic: `numpy.float64` is a `float` subclass and survives HA's encoder, but **`numpy.int64` is not an `int` subclass** and raises `TypeError: Type is not JSON serializable: numpy.int64`. `groupby().agg({'iWine':'count'})` produces exactly `int64`. Verified locally.

### Attribute payload budget

`recorder/db_schema.py:90` sets `MAX_STATE_ATTRS_BYTES = 16384`. When the serialised attribute dict exceeds it the recorder logs a warning and stores `{}` — discarding **all** attributes for that entity, on every state change. `by_producer` at 184 items is over that cap.

```python
_unrecorded_attributes = frozenset({"items"})
```

Unrecorded attributes are stripped before the size check, so this is what rescues it. It is a **hard requirement, not database hygiene.**

Budget: **≤ 8 KB serialised per entity.** A test serialises every entity's state and attributes through `homeassistant.helpers.json.json_bytes` and asserts the size, so a future field added to `items` fails CI rather than silently blanking attributes on users' installs.

Note what `_unrecorded_attributes` does **not** fix: attributes still ship over websocket to every connected client on every state change, and the more-info dialog renders the raw list. Roughly 40–60 KB across the slice entities per refresh. Unchanged data fires no `state_changed` event at all, so an idle cellar costs nothing. The payload budget, not the recorder exclusion, is the lever that matters here.

### Base class and update model

The current code builds on bare `Entity` with a hand-rolled double `Throttle`. That cannot deliver this design:

- `state_class` is only emitted as a capability attribute by `SensorEntity`.
- `Throttle` only stamps its timestamp on success, so during a CellarTracker outage every entity's 30-second poll retries the fetch — 47 attempts per 30 seconds, each logging an error.
- `setup()` blocks Home Assistant startup on a synchronous network call.

Replace with:

- `DataUpdateCoordinator(config_entry=None, update_interval=scan_interval)`, `_async_update_data` wrapping the sync client via `async_add_executor_job` and raising `UpdateFailed`
- `CoordinatorEntity` + `SensorEntity`, `should_poll = False`
- `always_update = False` so unchanged data fires no state write

`CoordinatorEntity.available` defaults to `coordinator.last_update_success`, meaning entities go unavailable on the first failed refresh. That is the **opposite** of the stale-data-tolerant behaviour a cellar inventory wants. Override `available` to stay `True` once any fetch has succeeded, and say so in the README.

### Identity and migration

Specified explicitly, because the first draft promised entity IDs that rested on nothing:

```python
_attr_unique_id = f"{DOMAIN}_by_{dimension}"            # slice
_attr_unique_id = f"{DOMAIN}_{dimension}_{slug}"        # per-value
_attr_has_entity_name = True
```

`unique_id` is name-independent so a later display-name change cannot orphan entities. Today's scheme derives `unique_id` from `name` and double-prefixes (`cellar_tracker.cellar_tracker.country.france`, `sensor.py:92-93`); it is abandoned, not migrated.

**Registry cleanup is required, not optional.** Old entities carry `unique_id`s and no config entry, so Home Assistant writes `unavailable` for every one of them at every start, indefinitely — the 30-day orphan purge only touches entries already marked deleted. Without cleanup, users are left with ~400 grey entities to delete by hand.

At setup, walk `entity_registry.async_get(hass).entities` for `platform == DOMAIN`, `async_remove` every entry whose `unique_id` is not in the new set, and log the count removed.

No `DeviceInfo` is possible without a config entry, so all 47 entities are device-less. Consistent with keeping config flow out of scope; noted so it is not mistaken for an oversight.

### Minimum Home Assistant version

`hacs.json` declares no floor. `_unrecorded_attributes` dates from ~2023.10. Declare `"homeassistant": "2024.6.0"` and set it in `hacs.json`.

## Dashboard

### Overview

mushroom chip row (total bottles, total value, average score, distinct producers) over a `statistics-graph` of `total_value`.

### Explore

One `flex-table-card` per dimension. Long tails read `items` from their slice entity; low-cardinality dimensions are listed from their per-value sensors directly.

Array expansion was verified against the card's docs rather than assumed — `docs/example-cfg-data.md:47`: *"Row expansion from a list will be automatically applied (by testing the selected data for being an `Array.isArray()`)"*, with dotted notation (`items.name`, `items.count`) selecting nested fields. `max_rows` caps the long tables.

**Unverified:** whether flex-table-card supports click-to-sort headers. `sort_by` sets a fixed sort at config time and `clickable` opens the entity popup; no header-sort option was found in `config-ref.md`. The spec claims fixed sorting only. Resolve before promising interactivity in the README.

### Composition — deferred

Cut from v1. sankey-chart's `nodes` are one-entity-one-scalar with **no array expansion**, and `links` take `source`/`target` as entity ids with `value` as *another entity*. A Country→Region→Producer sankey therefore needs ~217 node entities plus a joint count per link — and this model produces independent marginals, never joint counts. `attribute: items` yields a list, not a number.

A smaller sankey over the retained per-value entities (Color → Category → Country, 15 nodes) is plausible, but still needs joint counts the aggregation does not compute, and it is unconfirmed whether links weight correctly without a per-link `value` entity.

**Spike before committing to this view.** Until then `sankey-chart` is not a dependency.

### Dependencies

Checked 2026-09-14. The count column is GitHub's `open_issues_count`, which **bundles issues and pull requests**; it is not a pure issue count. Commit dates are the **default branch** — `pushed_at` covers any ref, including tags and side branches, and is not evidence that master is alive.

| Card | Last commit (default branch) | Latest release | Open issues + PRs | Use |
|---|---|---|---|---|
| mushroom | 2026-09-01 | v5.2.3 (2026-09) | 444 | chips, KPI row |
| flex-table-card | 2026-07-23 | v1.4 (2026-04) | 41 | slice tables |
| card-mod | 2026-02-08 | v4.2.1 (2026-02) | 12 | styling |

Three dependencies, down from four.

**Rejected:** `auto-entities` (release 2025-05, default branch last moved 2025-08) — designed out rather than depended on. `apexcharts-card` (release 2025-08) — nothing left needs it once Composition is deferred. `decluttering-card` (2023), `stack-in-card` (2020), `swipe-card` (2022), `template-entity-row` (2024) — unmaintained. `config-template-card` (release 2021) and `plotly-graph-card` (release 2024-09) — recent commits, stale releases, and HACS installs releases.

No custom Lovelace card will be written. This repo forks a semi-abandoned upstream; owning a JS build and tracking HA frontend API churn is a larger liability than any card it would replace.

## Error handling

- `pd.to_numeric` currently **raises on a non-numeric cell**, taking down the whole update. Measured: a blank string already coerces to `NaN` under the default, but `"N/A"` or any other junk raises `ValueError`. Switch to `errors="coerce"` and drop NaN per aggregation. All 1751 rows parse today; that is luck, not a guarantee.
- `CT` is 98% filled. Score aggregation skips unparseable values rather than failing the group.
- `Vintage` uses `1001` as the non-vintage sentinel, mapped to `NV` (behaviour preserved).
- `Currency` must be a valid ISO 4217 code or the frontend formats it wrong. Validate; fall back to no `device_class` if it is not.
- A failed refresh keeps the last good data and logs at warning. Entities are unavailable only until the first successful fetch.

## Testing

Aggregation currently lives inside `WineCellarData._update`, in a module that imports `homeassistant` at the top — plain `pytest` cannot import it.

**Extract the aggregation into a pure `aggregate.py` with no Home Assistant imports.** That is a precondition for testing, not a nice-to-have.

Cover: counts, percentages summing to 100, averages, the `1001`→`NV` mapping, blank `Valuation` coercion, groups where every `CT` is blank, empty inventory, native-type casting (no `numpy.int64` escapes), and the per-entity attribute size budget.

Fixtures are built from anonymised rows. The schema profile in the Evidence section was produced without exposing bottle-level data; fixtures follow the same rule.

## Breaking changes

Entity IDs change. Slice dimensions move to `sensor.cellar_tracker_by_producer`; per-value sensors keep a `sensor.cellar_tracker_country_france` shape but with a new `unique_id`, so they are new entities regardless. **Every existing dashboard breaks.** Accepted.

Required:

- Bump `manifest.json` `version` from `20210413`
- Add `"homeassistant": "2024.6.0"` to `hacs.json`
- Registry cleanup of orphaned entities (above)
- README rewritten: new card YAML, HACS frontend dependencies, explicit upgrade notice
- Old flex-table snippets removed, not left alongside the new ones
- CLAUDE.md updated: the double-`Throttle` description becomes wrong once the coordinator lands

## Out of scope

- **Drinking windows.** Deferred by decision, not by data: `BeginConsume`/`EndConsume` are 99% filled in `Inventory` and need no extra fetch. Sentinels are rare — one `9999`, twelve `1001`/`9999`. Measured distribution for whenever this is picked up: 8 bottles past peak, 24 closing this year, 75 in 1–2 years, 203 in 3–5, 490 in 6–10, 947 beyond 10, 391 not yet open. A plain "drink now" flag would match 77% of the cellar and carry no signal; bucket by urgency of `EndConsume` instead.
- **Composition view / sankey**, pending the spike above.
- `Consumed`, until its TSV corruption is understood.
- `List` (460 rows, per-wine `Quantity`) and `Availability` (433 rows, CT drinking-curve models) — both parse cleanly, neither is needed for this job.
- Config flow. Configuration stays YAML.
- Multi-currency. `ExchangeRate` is 1 throughout; revisit if that changes.
