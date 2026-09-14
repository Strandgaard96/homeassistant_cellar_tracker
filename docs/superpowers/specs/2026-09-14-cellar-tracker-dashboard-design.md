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
4. **The dashboard needs `auto-entities` only because of (1) and (2).** That card last released 2025-05-28, last touched master 2025-08-21, and carries 168 open issues.

## Architecture

### Sensor model

Replace per-value entities with **one entity per slice dimension**, carrying its full breakdown as a list attribute.

```
sensor.cellar_tracker_by_country       state: 8     (distinct values)
sensor.cellar_tracker_by_region        state: 25
sensor.cellar_tracker_by_subregion     state: 26
sensor.cellar_tracker_by_appellation   state: 64
sensor.cellar_tracker_by_producer      state: 184
sensor.cellar_tracker_by_varietal      state: 39
sensor.cellar_tracker_by_mastervarietal state: 38
sensor.cellar_tracker_by_vintage       state: 34
sensor.cellar_tracker_by_type          state: 9
sensor.cellar_tracker_by_color         state: 3
sensor.cellar_tracker_by_category      state: 4
sensor.cellar_tracker_by_size          state: 6
sensor.cellar_tracker_by_location      state: 4
sensor.cellar_tracker_by_store         state: 67
sensor.cellar_tracker_by_score_band    state: 6     (see score bands below)
```

Fifteen slice entities replacing 400+.

`Designation` (124), `Vineyard` (118) and `Locale` (69) are deliberately excluded: high cardinality, long tails of one or two bottles, and they duplicate information already carried by `Producer` and `Appellation`. Adding them later costs one line each in the `GROUPS` list.

**Score bands** (configurable; defaults chosen against the measured distribution, which puts 51% of the cellar in a single 3-point range):

`<90` · `90–91.9` · `92–92.9` · `93–93.9` · `94–94.9` · `95+`

Six bands, split finest where the mass actually sits. The coarser five-band table under Evidence describes the raw distribution, not these defaults.

Each carries:

```yaml
items:
  - name: France
    count: 612
    pct: 34.9
    value_total: 412300.0
    value_avg: 673.7
    score_avg: 93.1
```

Slice entities carry no `unit_of_measurement`; their state is a count of distinct values, not a physical quantity. `items` is sorted by `count` descending. `score_avg` is the mean `CT` over rows in that group where `CT` parses; omitted when no row in the group has a score.

### Scalars

Four numeric sensors, properly typed so Home Assistant records them:

| Entity | state_class | device_class | unit |
|---|---|---|---|
| `sensor.cellar_tracker_total_bottles` | `measurement` | — | `bottles` |
| `sensor.cellar_tracker_total_value` | `measurement` | `monetary` | `DKK` |
| `sensor.cellar_tracker_average_value` | `measurement` | `monetary` | `DKK` |
| `sensor.cellar_tracker_average_score` | `measurement` | — | `points` |

Currency comes from the `Currency` column (the most common value across rows, should it ever vary), not `hass.config.currency`, and the value is a bare float. This is what unlocks native `statistics-graph` for value over time — no charting dependency required.

### Recorder pressure

`items` on `by_producer` is 184 entries. Recording that every scan interval would bloat the database for no benefit — the attributes are derived, not observed.

All slice entities set:

```python
_unrecorded_attributes = frozenset({"items"})
```

States stay recorded (cardinality over time is genuinely interesting); the payloads do not. Per-bottle lists are never placed in attributes at all.

### Dynamic values without restart

Because group values are attribute rows rather than entities, a newly added producer appears on the next refresh with no restart and no registry change. This removes the need for `auto-entities` entirely.

## Dashboard

Three views.

**Overview** — mushroom chip row (bottles, total value, average score, distinct producers) over a `statistics-graph` of `total_value`, which now has real history.

**Explore** — one `flex-table-card` per slice dimension, reading `items` from the corresponding entity. Sortable by count, value or score. Card config is static YAML with no wildcards; contents follow the data.

This rests on flex-table-card expanding an array attribute into rows, which was verified against its docs rather than assumed — `docs/example-cfg-data.md`: *"Row expansion from a list will be automatically applied (by testing the selected data for being an `Array.isArray()`)"*, with dotted notation (`items.name`, `items.count`) selecting nested fields. `max_rows` caps the long tables (`by_producer` is 184 rows).

**Composition** — `sankey-chart` flowing Country → Region → Producer, plus the 1-point-bin `CT` histogram.

### Dependencies

Every dependency was checked for maintenance health on 2026-09-14.

| Card | Last commit | Latest release | Issues | Use |
|---|---|---|---|---|
| mushroom | 2026-09-01 | v5.2.3 (2026-09) | 444 | chips, KPI row |
| card-mod | 2026-02-08 | v4.2.1 (2026-02) | 12 | styling |
| flex-table-card | 2026-07-23 | v1.4 (2026-04) | 41 | slice tables |
| sankey-chart | 2026-06-01 | v6.3.0 (2026-06) | 27 | composition |

Explicitly **rejected**:

- `auto-entities` — v1.16.1 (2025-05), master idle since 2025-08, 168 issues. Designed out rather than depended on.
- `apexcharts-card` — v2.2.3 (2025-08), 52 issues. Replaced by native `statistics-graph` plus `sankey-chart`.
- `decluttering-card` (2023), `stack-in-card` (2020), `swipe-card` (2022), `template-entity-row` (2024) — unmaintained.
- `config-template-card` (release 2021) and `plotly-graph-card` (release 2024-09) — recent commits but stale releases, and HACS installs releases.

No custom Lovelace card will be written. This repo is a fork of a semi-abandoned upstream; owning a JS build and tracking HA frontend API churn is a larger maintenance liability than any card it would replace.

## Error handling

- `Valuation` and `Price` currently go through `pd.to_numeric`, which **raises** on a blank or non-numeric cell and takes down the whole update. Switch to `errors="coerce"` and drop NaN per aggregation. All 1751 rows parse today; that is luck, not a guarantee.
- `CT` is 98% filled. Score aggregation skips unparseable values rather than failing the group.
- `Vintage` uses `1001` as the non-vintage sentinel; it maps to `NV` (behaviour preserved from current code).
- A failed fetch leaves the previous data in place and logs at warning; entities go unavailable only if there has never been a successful fetch.

## Testing

No test suite exists today. Add `pytest` with fixtures built from **anonymised** real inventory rows — the schema profile in this document was produced without exposing bottle-level data, and fixtures follow the same rule.

Cover: aggregation maths (counts, percentages sum to 100, averages), the `1001`→`NV` mapping, blank-`Valuation` coercion, groups where every `CT` is blank, and an empty inventory.

## Breaking changes

Entity IDs change from `sensor.cellar_tracker_country_france` to `sensor.cellar_tracker_by_country`. **Every existing user's dashboard breaks.** This is accepted.

Required:

- Bump `manifest.json` `version` from `20210413`
- README rewritten: new card YAML, new HACS frontend dependencies, explicit upgrade notice
- Old flex-table snippets removed, not left alongside the new ones

## Out of scope

- **Drinking windows.** Deferred by decision, not by data: `BeginConsume` and `EndConsume` are **99% filled** in `Inventory` and need no extra fetch. Sentinels are rare — one `9999`, twelve `1001`/`9999`. Measured distribution, for whenever this is picked up: 8 bottles past peak, 24 closing this year, 75 in 1–2 years, 203 in 3–5, 490 in 6–10, 947 beyond 10, 391 not yet open. Note that a plain "drink now" flag would match 77% of the cellar and carry no signal; bucket by urgency of `EndConsume` instead.
- `Consumed`, until its TSV corruption is understood.
- `List` (460 rows, per-wine `Quantity`) and `Availability` (433 rows, CT drinking-curve models) — both parse cleanly, neither is needed for this job.
- Config flow. Configuration stays YAML.
- Multi-currency. `ExchangeRate` is 1 throughout; revisit if that changes.
