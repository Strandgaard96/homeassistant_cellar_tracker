# Cellar Tracker Sensor Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ~400 string-valued, restart-frozen sensors with 47 correctly-typed entities driven by a `DataUpdateCoordinator`, and ship a dashboard that needs no unmaintained frontend cards.

**Architecture:** All pandas aggregation moves into a pure `aggregate.py` with zero Home Assistant imports, so it is testable with plain pytest. A `DataUpdateCoordinator` owns fetching and replaces the hand-rolled double `Throttle`. Entities split by cardinality: six low-cardinality dimensions become 34 per-value numeric sensors usable in automations and voice; eight long-tail dimensions plus score bands become 9 slice entities carrying an `items` list attribute excluded from the recorder.

**Tech Stack:** Python 3.13, pandas, Home Assistant 2024.6+, pytest, ruff, ty. Frontend: mushroom, flex-table-card, card-mod (all HACS).

**Spec:** `docs/superpowers/specs/2026-09-14-cellar-tracker-dashboard-design.md`

## Global Constraints

- **Minimum Home Assistant: 2024.6.0.** Declare in `hacs.json` as `"homeassistant": "2024.6.0"`.
- **`device_class: monetary` requires `state_class: total`.** `measurement` is invalid with it — `sensor/const.py:844` maps `MONETARY` to `{TOTAL}` only. Averages get no `device_class`.
- **No `numpy` scalars in attributes or states.** `numpy.float64` is a `float` subclass and passes HA's encoder; `numpy.int64` is **not** an `int` subclass and raises `TypeError: Type is not JSON serializable: numpy.int64`. Cast with `int()` / `float()`.
- **Attribute payload budget: ≤ 12 KiB serialised per entity, and `items` is capped at the top 100 entries by count.** Hard cap is `MAX_STATE_ATTRS_BYTES = 16384` (`recorder/db_schema.py:90`); over it the recorder stores `{}` for the entity's *entire* attribute dict. Measured: all 184 producers serialise to **17,112 bytes**, over the hard cap — hence the limit. 100 entries measure 9,300 bytes at realistic name lengths.
- **`_unrecorded_attributes` must be a class attribute.** Instance attributes are ignored by the recorder.
- **`homeassistant` IS installed in the test environment.** Measured: HA 2026.2.3 resolves alongside pandas and the full suite runs in ~2.3s. Modules may import Home Assistant at module level normally. `aggregate.py` and `naming.py` still stay HA-free, but for separation of concerns, not testability.
- **Three frontend dependencies only:** mushroom, flex-table-card, card-mod. No `auto-entities`, no `apexcharts-card`, no `sankey-chart`, no custom Lovelace card.
- **Run tests with:** `uv run --with homeassistant --with pytest --with pandas pytest tests -q` from the repo root. Verified working.
- **Lint gate:** `uvx ruff check .` and `uvx ty check` must both pass before every commit.
- **Do not run `ruff format`.** `__init__.py` uses three-space indents; formatting rewrites the whole file and destroys blame. Out of scope.
- **Never use `git add -A`.** Stage named paths only.

## File Structure

| File | Responsibility |
|---|---|
| `custom_components/cellar_tracker/const.py` | **Create.** `DOMAIN`, dimension→column maps, default score bands, sentinels. No logic. |
| `custom_components/cellar_tracker/aggregate.py` | **Create.** Pure. All pandas. Takes raw rows, returns dataclasses. No HA imports. |
| `custom_components/cellar_tracker/naming.py` | **Create.** Pure. `slugify`, `unique_slugs`, `expected_unique_ids`. No HA imports — `tests/test_slug.py` imports it. |
| `custom_components/cellar_tracker/coordinator.py` | **Create.** `CellarTrackerCoordinator(DataUpdateCoordinator)`. Owns fetch + `UpdateFailed`. |
| `custom_components/cellar_tracker/sensor.py` | **Rewrite.** Three entity classes + platform setup. |
| `custom_components/cellar_tracker/__init__.py` | **Rewrite.** Config schema, coordinator wiring, registry cleanup. |
| `custom_components/cellar_tracker/manifest.json` | **Modify.** Version bump. |
| `hacs.json` | **Modify.** Add HA version floor. |
| `tests/fixtures.py` | **Create.** Anonymised inventory rows. |
| `tests/test_aggregate.py` | **Create.** Aggregation maths, sentinels, coercion, native types. |
| `tests/test_payload_size.py` | **Create.** Attribute budget enforcement. |
| `pyproject.toml` | **Modify.** pytest config. |
| `docs/dashboard/*.yaml` | **Create.** Dashboard YAML, one file per view. |
| `README.md` | **Rewrite.** New cards, new deps, upgrade notice. |
| `CLAUDE.md` | **Modify.** Double-`Throttle` description becomes wrong. |

---

### Task 1: Test scaffolding and anonymised fixture

**Files:**
- Create: `tests/fixtures.py`
- Create: `tests/test_fixtures.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: nothing.
- Produces: `SAMPLE_ROWS: list[dict[str, str]]` — inventory rows with every column the aggregation reads, all values as `str` (CellarTracker returns TSV, so everything is a string).

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures.py`. Every value is a string, mirroring `csv.DictReader` output. Rows deliberately include a blank `Valuation`, a blank `CT`, and the `1001` non-vintage sentinel.

```python
"""Anonymised inventory rows shaped like CellarTracker TSV output.

Every value is a str: cellartracker parses with csv.DictReader, so no
type conversion has happened yet by the time our code sees the rows.
"""

def _row(**overrides):
    base = {
        "iWine": "1000001",
        "Valuation": "100.0",
        "Price": "80.0",
        "Currency": "DKK",
        "CT": "90.0",
        "Vintage": "2018",
        "Country": "France",
        "Region": "Bordeaux",
        "SubRegion": "Medoc",
        "Appellation": "Pauillac",
        "Producer": "Producer A",
        "Varietal": "Cabernet Sauvignon",
        "MasterVarietal": "Cabernet Sauvignon",
        "Type": "Red",
        "Color": "Red",
        "Category": "Dry",
        "Size": "750ml",
        "Location": "Cellar",
        "StoreName": "Store A",
    }
    base.update(overrides)
    return base


SAMPLE_ROWS = [
    _row(iWine="1", Valuation="100.0", CT="90.0"),
    _row(iWine="2", Valuation="200.0", CT="94.0"),
    _row(iWine="3", Country="Italy", Region="Tuscany", Producer="Producer B",
         Color="Red", Valuation="300.0", CT="96.0"),
    _row(iWine="4", Country="Italy", Region="Tuscany", Producer="Producer B",
         Color="White", Type="White", Valuation="", CT="88.0"),
    _row(iWine="5", Vintage="1001", Producer="Producer C",
         Valuation="400.0", CT=""),
]
```

- [ ] **Step 2: Write a test that the fixture is well-formed**

Create `tests/test_fixtures.py`:

```python
from tests.fixtures import SAMPLE_ROWS


def test_every_row_has_identical_keys():
    keys = set(SAMPLE_ROWS[0])
    for row in SAMPLE_ROWS:
        assert set(row) == keys


def test_every_value_is_a_string():
    for row in SAMPLE_ROWS:
        for key, value in row.items():
            assert isinstance(value, str), f"{key} is {type(value)}"


def test_fixture_covers_the_awkward_cases():
    assert any(r["Valuation"] == "" for r in SAMPLE_ROWS), "need a blank valuation"
    assert any(r["CT"] == "" for r in SAMPLE_ROWS), "need a blank score"
    assert any(r["Vintage"] == "1001" for r in SAMPLE_ROWS), "need the NV sentinel"
```

- [ ] **Step 3: Add pytest config**

Append to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`pythonpath = ["."]` lets `from tests.fixtures import ...` and `from custom_components.cellar_tracker import ...` resolve without installing anything.

- [ ] **Step 4: Run the tests**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests -q`
Expected: PASS, 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures.py tests/test_fixtures.py pyproject.toml
git commit -m "test: add anonymised inventory fixture and pytest config"
```

---

### Task 2: Constants module

**Files:**
- Create: `custom_components/cellar_tracker/const.py`
- Test: `tests/test_const.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DOMAIN: str`
  - `LOW_CARDINALITY: dict[str, str]` — slug → inventory column, 6 entries
  - `LONG_TAIL: dict[str, str]` — slug → inventory column, 8 entries
  - `DEFAULT_SCORE_BANDS: tuple[tuple[float | None, float | None, str], ...]` — `(lower_inclusive, upper_exclusive, label)`
  - `NV_SENTINEL: str`, `NV_LABEL: str`
  - `SCORE_COLUMN: str`, `VALUATION_COLUMN: str`, `CURRENCY_COLUMN: str`, `COUNT_COLUMN: str`
  - `MAX_ATTR_BYTES: int`

- [ ] **Step 1: Write the failing test**

Create `tests/test_const.py`:

```python
from custom_components.cellar_tracker import const


def test_dimension_sets_are_disjoint():
    assert not (set(const.LOW_CARDINALITY) & set(const.LONG_TAIL))


def test_expected_dimension_counts():
    assert len(const.LOW_CARDINALITY) == 6
    assert len(const.LONG_TAIL) == 8


def test_score_bands_are_contiguous_and_cover_everything():
    bands = const.DEFAULT_SCORE_BANDS
    assert bands[0][0] is None, "first band must be open-ended below"
    assert bands[-1][1] is None, "last band must be open-ended above"
    for (_, upper, _), (lower, _, _) in zip(bands, bands[1:]):
        assert upper == lower, f"gap or overlap between {upper} and {lower}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests/test_const.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'custom_components.cellar_tracker.const'`

- [ ] **Step 3: Write the implementation**

Create `custom_components/cellar_tracker/const.py`:

```python
"""Constants for the Cellar Tracker integration.

Dimension maps are slug -> CellarTracker inventory column name. The slug
becomes part of the entity_id, so changing one renames entities.
"""

DOMAIN = "cellar_tracker"

# Dimensions small enough that one sensor per value is worth it: these work
# in numeric_state triggers, templates and voice assistants.
LOW_CARDINALITY = {
    "country": "Country",
    "type": "Type",
    "size": "Size",
    "category": "Category",
    "location": "Location",
    "color": "Color",
}

# Long tails. One entity each, breakdown in an `items` list attribute.
LONG_TAIL = {
    "producer": "Producer",
    "store": "StoreName",
    "appellation": "Appellation",
    "varietal": "Varietal",
    "mastervarietal": "MasterVarietal",
    "vintage": "Vintage",
    "subregion": "SubRegion",
    "region": "Region",
}

# (lower inclusive, upper exclusive, label). None means open-ended.
# Split finest around 90-95, where the measured distribution puts most of
# the cellar; see the spec's Evidence section.
DEFAULT_SCORE_BANDS = (
    (None, 90.0, "<90"),
    (90.0, 92.0, "90-91.9"),
    (92.0, 93.0, "92-92.9"),
    (93.0, 94.0, "93-93.9"),
    (94.0, 95.0, "94-94.9"),
    (95.0, None, "95+"),
)

# CellarTracker uses vintage 1001 to mean non-vintage.
NV_SENTINEL = "1001"
NV_LABEL = "NV"

SCORE_COLUMN = "CT"
VALUATION_COLUMN = "Valuation"
CURRENCY_COLUMN = "Currency"
COUNT_COLUMN = "iWine"

# Recorder discards an entity's whole attribute dict above 16384 bytes
# (recorder/db_schema.py:90). Budget 12 KiB for margin.
MAX_ATTR_BYTES = 12288

# All 184 producers serialise to 17112 bytes, over the hard cap. The
# Explore card renders 50 rows, so 100 is already double what is shown.
ITEMS_LIMIT = 100
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests/test_const.py -q`
Expected: PASS, 3 passed.

- [ ] **Step 5: Lint and commit**

```bash
uvx ruff check . && uvx ty check
git add custom_components/cellar_tracker/const.py tests/test_const.py
git commit -m "feat: add constants module with dimension maps and score bands"
```

---

### Task 3: Pure aggregation — grouping and native types

**Files:**
- Create: `custom_components/cellar_tracker/aggregate.py`
- Test: `tests/test_aggregate.py`

**Interfaces:**
- Consumes: `const.LOW_CARDINALITY`, `const.LONG_TAIL`, `const.DEFAULT_SCORE_BANDS`, `const.NV_SENTINEL`, `const.NV_LABEL`, `const.SCORE_COLUMN`, `const.VALUATION_COLUMN`, `const.CURRENCY_COLUMN`, `const.COUNT_COLUMN`
- Produces:
  - `@dataclass GroupItem` with fields `name: str`, `count: int`, `value_avg: float`, `score_avg: float | None`
  - `@dataclass CellarData` with fields `low: dict[str, list[GroupItem]]`, `tails: dict[str, list[GroupItem]]`, `total_bottles: int`, `total_value: float`, `average_value: float`, `average_score: float | None`, `currency: str`
  - `def aggregate(rows: list[dict[str, str]], score_bands=DEFAULT_SCORE_BANDS) -> CellarData`

- [ ] **Step 1: Write the failing test**

Create `tests/test_aggregate.py`:

```python
import pytest

from custom_components.cellar_tracker.aggregate import aggregate
from tests.fixtures import SAMPLE_ROWS


@pytest.fixture
def data():
    return aggregate(SAMPLE_ROWS)


def test_total_bottles_counts_rows(data):
    assert data.total_bottles == 5


def test_country_groups_sorted_by_count_descending(data):
    names = [item.name for item in data.low["country"]]
    assert names == ["France", "Italy"]
    assert data.low["country"][0].count == 3


def test_long_tail_dimension_is_populated(data):
    producers = {item.name: item.count for item in data.tails["producer"]}
    assert producers == {"Producer A": 2, "Producer B": 2, "Producer C": 1}


def test_counts_are_native_ints_not_numpy(data):
    for item in data.low["country"]:
        assert type(item.count) is int, f"got {type(item.count)}"


def test_values_are_native_floats_not_numpy(data):
    for item in data.low["country"]:
        assert type(item.value_avg) is float, f"got {type(item.value_avg)}"
    assert type(data.total_value) is float
    assert type(data.average_value) is float


def test_currency_is_read_from_the_data(data):
    assert data.currency == "DKK"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests/test_aggregate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'custom_components.cellar_tracker.aggregate'`

- [ ] **Step 3: Write the implementation**

Create `custom_components/cellar_tracker/aggregate.py`. Note there are **no Home Assistant imports** — that is the point of this module.

```python
"""Pure aggregation over a CellarTracker inventory export.

Imports no Home Assistant module, so it can be tested with plain pytest.
Everything arriving here is a str, because cellartracker parses TSV with
csv.DictReader.

Every number leaving here is a native Python int or float. pandas hands
back numpy scalars, and numpy.int64 is not an int subclass, so it raises
TypeError in Home Assistant's JSON encoder.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from .const import (
    COUNT_COLUMN,
    CURRENCY_COLUMN,
    DEFAULT_SCORE_BANDS,
    LONG_TAIL,
    LOW_CARDINALITY,
    NV_LABEL,
    NV_SENTINEL,
    SCORE_COLUMN,
    VALUATION_COLUMN,
)


@dataclass
class GroupItem:
    """One row of a breakdown: a distinct value and its aggregates."""

    name: str
    count: int
    value_avg: float
    score_avg: float | None = None


@dataclass
class CellarData:
    """Everything the sensors need, derived from one inventory fetch."""

    low: dict[str, list[GroupItem]] = field(default_factory=dict)
    tails: dict[str, list[GroupItem]] = field(default_factory=dict)
    total_bottles: int = 0
    total_value: float = 0.0
    average_value: float = 0.0
    average_score: float | None = None
    currency: str = ""


def _group(df: pd.DataFrame, column: str) -> list[GroupItem]:
    """Aggregate one column into GroupItems, sorted by count descending."""
    items: list[GroupItem] = []
    for name, chunk in df.groupby(column, dropna=False):
        valuations = chunk[VALUATION_COLUMN].dropna()
        scores = chunk[SCORE_COLUMN].dropna()
        items.append(
            GroupItem(
                name=str(name),
                count=int(len(chunk)),
                value_avg=round(float(valuations.mean()), 2) if len(valuations) else 0.0,
                score_avg=round(float(scores.mean()), 2) if len(scores) else None,
            )
        )
    items.sort(key=lambda item: (-item.count, item.name))
    return items


def aggregate(
    rows: list[dict[str, str]],
    score_bands=DEFAULT_SCORE_BANDS,
) -> CellarData:
    """Turn raw inventory rows into everything the sensors expose."""
    if not rows:
        return CellarData()

    df = pd.DataFrame(rows)

    # errors="coerce" turns a blank or junk cell into NaN. The previous
    # implementation used the default, which raises and kills the whole
    # update over one bad cell.
    for column in (VALUATION_COLUMN, SCORE_COLUMN):
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    data = CellarData()
    data.total_bottles = int(len(df))

    valuations = df[VALUATION_COLUMN].dropna() if VALUATION_COLUMN in df else pd.Series(dtype=float)
    data.total_value = round(float(valuations.sum()), 2) if len(valuations) else 0.0
    data.average_value = round(float(valuations.mean()), 2) if len(valuations) else 0.0

    scores = df[SCORE_COLUMN].dropna() if SCORE_COLUMN in df else pd.Series(dtype=float)
    data.average_score = round(float(scores.mean()), 2) if len(scores) else None

    if CURRENCY_COLUMN in df:
        currencies = [value for value in df[CURRENCY_COLUMN].tolist() if value]
        data.currency = Counter(currencies).most_common(1)[0][0] if currencies else ""

    for slug, column in LOW_CARDINALITY.items():
        if column in df:
            data.low[slug] = _group(df, column)

    for slug, column in LONG_TAIL.items():
        if column in df:
            data.tails[slug] = _group(df, column)

    return data


__all__ = ["CellarData", "GroupItem", "aggregate", "COUNT_COLUMN", "NV_LABEL", "NV_SENTINEL"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests/test_aggregate.py -q`
Expected: PASS, 6 passed.

- [ ] **Step 5: Lint and commit**

```bash
uvx ruff check . && uvx ty check
git add custom_components/cellar_tracker/aggregate.py tests/test_aggregate.py
git commit -m "feat: add pure aggregation module with native type casting"
```

---

### Task 4: Aggregation — NV sentinel, blank coercion, score bands, empty input

**Files:**
- Modify: `custom_components/cellar_tracker/aggregate.py`
- Test: `tests/test_aggregate.py` (append)

**Interfaces:**
- Consumes: everything from Task 3.
- Produces: `CellarData.tails["score_band"]` populated; `vintage` group labels `1001` as `NV`.

- [ ] **Step 1: Write the failing tests**

First change the **existing** import line at the top of `tests/test_aggregate.py` to also bring in `CellarData`:

```python
from custom_components.cellar_tracker.aggregate import CellarData, aggregate
```

Do not append a second import lower down: ruff selects `E`, and `E402 module-level-import-not-at-top-of-file` would fail the lint gate.

Then append the tests:

```python
def test_vintage_1001_is_relabelled_nv(data):
    labels = [item.name for item in data.tails["vintage"]]
    assert "NV" in labels
    assert "1001" not in labels


def test_blank_valuation_is_coerced_not_raised(data):
    # Row 4 has Valuation="". Five bottles, four priced: 100+200+300+400.
    assert data.total_value == 1000.0
    assert data.average_value == 250.0


def test_blank_score_is_excluded_from_the_average(data):
    # Row 5 has CT="". Four scored: 90+94+96+88 = 368 / 4 = 92.0
    assert data.average_score == 92.0


def test_group_with_no_scores_reports_none():
    rows = [
        {"iWine": "1", "Country": "Spain", "Valuation": "10.0", "CT": "", "Currency": "DKK"},
    ]
    result = aggregate(rows)
    assert result.low["country"][0].score_avg is None


def test_score_bands_bucket_by_ct(data):
    bands = {item.name: item.count for item in data.tails["score_band"]}
    # 90.0 -> "90-91.9", 94.0 -> "94-94.9", 96.0 -> "95+", 88.0 -> "<90"
    assert bands["90-91.9"] == 1
    assert bands["94-94.9"] == 1
    assert bands["95+"] == 1
    assert bands["<90"] == 1
    # The unscored row is not bucketed at all.
    assert sum(bands.values()) == 4


def test_empty_inventory_returns_empty_data():
    result = aggregate([])
    assert isinstance(result, CellarData)
    assert result.total_bottles == 0
    assert result.total_value == 0.0
    assert result.average_score is None
    assert result.low == {}
    assert result.tails == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests/test_aggregate.py -q`
Expected: FAIL — `KeyError: 'score_band'` and `assert 'NV' in ['1001', '2018']`

- [ ] **Step 3: Write the implementation**

In `aggregate.py`, add a banding helper above `aggregate`:

```python
def _band_for(score: float, score_bands) -> str | None:
    """Return the label of the band this score falls in."""
    for lower, upper, label in score_bands:
        if (lower is None or score >= lower) and (upper is None or score < upper):
            return label
    return None


def _score_band_items(df: pd.DataFrame, score_bands) -> list[GroupItem]:
    """Bucket scored rows into bands. Unscored rows are not bucketed."""
    scored = df[df[SCORE_COLUMN].notna()]
    items: list[GroupItem] = []
    for _, upper, label in _ordered(score_bands):
        chunk = scored[scored[SCORE_COLUMN].map(lambda s: _band_for(float(s), score_bands) == label)]
        if not len(chunk):
            continue
        valuations = chunk[VALUATION_COLUMN].dropna()
        items.append(
            GroupItem(
                name=label,
                count=int(len(chunk)),
                value_avg=round(float(valuations.mean()), 2) if len(valuations) else 0.0,
                score_avg=round(float(chunk[SCORE_COLUMN].mean()), 2),
            )
        )
    items.sort(key=lambda item: (-item.count, item.name))
    return items


def _ordered(score_bands):
    """Bands in configured order. Kept separate so callers cannot mutate."""
    return tuple(score_bands)
```

In `aggregate`, relabel the non-vintage sentinel immediately after building the DataFrame, before any grouping:

```python
    df = pd.DataFrame(rows)

    # CellarTracker encodes non-vintage as 1001. Relabel before grouping so
    # the label rather than the sentinel reaches the entity.
    if LONG_TAIL["vintage"] in df:
        df[LONG_TAIL["vintage"]] = df[LONG_TAIL["vintage"]].replace(NV_SENTINEL, NV_LABEL)
```

And at the end of `aggregate`, before `return data`:

```python
    if SCORE_COLUMN in df:
        data.tails["score_band"] = _score_band_items(df, score_bands)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests -q`
Expected: PASS, 15 passed.

- [ ] **Step 5: Lint and commit**

```bash
uvx ruff check . && uvx ty check
git add custom_components/cellar_tracker/aggregate.py tests/test_aggregate.py
git commit -m "feat: add score bands, NV relabelling and blank-cell coercion"
```

---

### Task 5: Attribute payload budget test

**Files:**
- Create: `tests/test_payload_size.py`

**Interfaces:**
- Consumes: `aggregate`, `GroupItem`, `const.MAX_ATTR_BYTES`
- Produces: `items_payload(items: list[GroupItem]) -> list[dict]` in `aggregate.py` — the exact dict shape that becomes the `items` attribute.

This task exists because exceeding 16384 bytes makes the recorder silently store `{}` for an entity's entire attribute dict. A future field added to `items` must fail CI, not fail on users' installs.

- [ ] **Step 1: Write the failing test**

Create `tests/test_payload_size.py`:

```python
import json

from custom_components.cellar_tracker.aggregate import aggregate, items_payload
from custom_components.cellar_tracker.const import ITEMS_LIMIT, MAX_ATTR_BYTES
from tests.fixtures import SAMPLE_ROWS


def test_measured_constants_are_pinned():
    """These are measurements, not preferences.

    MAX_ATTR_BYTES leaves margin under Home Assistant's 16384-byte recorder
    cap; ITEMS_LIMIT exists because all 184 producer entries serialise to
    17112 bytes, over that cap. Raising either without re-measuring
    reintroduces the bug this rewrite fixed, so pin them.
    """
    assert MAX_ATTR_BYTES == 12288
    assert ITEMS_LIMIT == 100
    assert MAX_ATTR_BYTES < 16384, "must stay under the recorder's hard cap"


def test_payload_shape_has_no_derived_fields():
    # pct and value_total are computed in the frontend, not stored: it cuts
    # roughly 35% off the largest payload.
    payload = items_payload(aggregate(SAMPLE_ROWS).tails["producer"])
    assert set(payload[0]) == {"name", "count", "value_avg", "score_avg"}


def test_payload_is_json_serialisable_with_native_types():
    payload = items_payload(aggregate(SAMPLE_ROWS).tails["producer"])
    encoded = json.dumps(payload)  # raises TypeError on numpy scalars
    assert encoded


def test_payload_is_capped_and_within_budget():
    # 184 producers is the measured worst case for this cellar, and all of
    # them serialise to 17112 bytes -- over the recorder's 16384 hard cap.
    # Hence ITEMS_LIMIT.
    rows = []
    for index in range(184):
        for _ in range(10):
            rows.append({
                "iWine": str(index),
                "Producer": f"Chateau Example Number {index:03d}",
                "Valuation": "1234.56",
                "CT": "93.5",
                "Currency": "DKK",
            })
    items = aggregate(rows).tails["producer"]
    assert len(items) == 184, "aggregation keeps every group"

    payload = items_payload(items)
    assert len(payload) == ITEMS_LIMIT, "the attribute is capped"
    size = len(json.dumps(payload).encode())
    assert size <= MAX_ATTR_BYTES, f"payload is {size} bytes, budget is {MAX_ATTR_BYTES}"


def test_uncapped_payload_would_have_blown_the_recorder_cap():
    # Guards the reason ITEMS_LIMIT exists, so nobody quietly removes it.
    rows = [
        {"iWine": str(i), "Producer": f"Chateau Example Number {i:03d}",
         "Valuation": "1234.56", "CT": "93.5", "Currency": "DKK"}
        for i in range(184)
    ]
    items = aggregate(rows).tails["producer"]
    uncapped = items_payload(items, limit=None)
    assert len(json.dumps(uncapped).encode()) > 16384
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests/test_payload_size.py -q`
Expected: FAIL with `ImportError: cannot import name 'items_payload'`

- [ ] **Step 3: Write the implementation**

Add to `aggregate.py`:

```python
def items_payload(
    items: list[GroupItem],
    limit: int | None = ITEMS_LIMIT,
) -> list[dict[str, object]]:
    """The exact dict shape that becomes an entity's `items` attribute.

    pct and value_total are deliberately absent: both are derivable
    (pct = count / total_bottles, value_total = count * value_avg) and
    dropping them cuts roughly 35% off the largest payload.

    `limit` caps the list because all 184 producers serialise to 17112
    bytes, over the recorder's 16384-byte cap. Items arrive sorted by
    count descending, so the cap drops the long tail. Pass limit=None
    only in tests that measure the uncapped size.
    """
    selected = items if limit is None else items[:limit]
    return [
        {
            "name": item.name,
            "count": item.count,
            "value_avg": item.value_avg,
            "score_avg": item.score_avg,
        }
        for item in selected
    ]
```

Import `ITEMS_LIMIT` from `.const` and add `"items_payload"` to `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests -q`
Expected: PASS, 19 passed.

If the budget test fails, the fix is to shorten the payload, not to raise `MAX_ATTR_BYTES`.

- [ ] **Step 5: Lint and commit**

```bash
uvx ruff check . && uvx ty check
git add custom_components/cellar_tracker/aggregate.py tests/test_payload_size.py
git commit -m "test: enforce attribute payload budget against recorder cap"
```

---

### Task 6: Coordinator

**Files:**
- Create: `custom_components/cellar_tracker/coordinator.py`

**Interfaces:**
- Consumes: `aggregate.aggregate`, `aggregate.CellarData`, `const.DOMAIN`
- Produces: `class CellarTrackerCoordinator(DataUpdateCoordinator[CellarData])` with `__init__(hass, username, password, scan_interval, score_bands)` and attribute `.data: CellarData`

There is no unit test for this task: it needs a running Home Assistant. It is verified in Task 11 by loading the integration.

- [ ] **Step 1: Write the implementation**

Create `custom_components/cellar_tracker/coordinator.py`:

```python
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
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `uvx ruff check . && uvx ty check`
Expected: both clean. `ty` will not resolve `homeassistant` or `cellartracker`; `unresolved-import` is already ignored in `pyproject.toml`.

- [ ] **Step 3: Commit**

```bash
git add custom_components/cellar_tracker/coordinator.py
git commit -m "feat: add DataUpdateCoordinator replacing double Throttle"
```

---

### Task 7: Naming module and entity classes

**Files:**
- Create: `custom_components/cellar_tracker/naming.py`
- Rewrite: `custom_components/cellar_tracker/sensor.py`

**Why two files:** entity identity (slugs, unique IDs, the set of IDs we provide) is pure data logic with its own tests. Keeping it out of `sensor.py` lets Task 9's registry cleanup and Task 10's setup import it without pulling in entity classes.

**Interfaces:**
- Consumes: `CellarTrackerCoordinator`, `aggregate.items_payload`, `const.LOW_CARDINALITY`, `const.LONG_TAIL`, `const.DOMAIN`
- Produces: `async_setup_platform`, and the classes `CellarValueSensor`, `CellarSliceSensor`, `CellarScalarSensor`, plus `build_entities(coordinator) -> list[SensorEntity]` and `expected_unique_ids(data) -> set[str]` (Task 9 consumes the latter).

Naming note: the spec suggested `_attr_has_entity_name = True`. This plan does **not** use it. Without a config entry there is no device, and `has_entity_name` is defined relative to a device; setting `_attr_name` directly gives predictable, verifiable entity IDs instead.

- [ ] **Step 1: Write the naming module**

Create `custom_components/cellar_tracker/naming.py`. Keep it free of Home Assistant imports: it is pure identity logic.

```python
"""Entity identity: slugs, unique IDs, and the set of IDs we provide.

Imports no Home Assistant module so it can be tested with plain pytest.
"""

from __future__ import annotations

import re

from .aggregate import CellarData
from .const import DOMAIN, LONG_TAIL, LOW_CARDINALITY

SCALAR_KEYS = ("total_bottles", "total_value", "average_value", "average_score")
SLICE_DIMENSIONS = tuple(LONG_TAIL) + ("score_band",)


def slugify(value: str) -> str:
    """Lowercase and collapse anything non-alphanumeric to a single _."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def expected_unique_ids(data: CellarData) -> set[str]:
    """Unique IDs the new model produces. Task 9 removes everything else."""
    ids = {f"{DOMAIN}_by_{dimension}" for dimension in SLICE_DIMENSIONS}
    ids |= {f"{DOMAIN}_{key}" for key in SCALAR_KEYS}
    for dimension in LOW_CARDINALITY:
        for item in data.low.get(dimension, []):
            ids.add(f"{DOMAIN}_{dimension}_{slugify(item.name)}")
    return ids
```

Task 8 replaces the bare `slugify` calls here with collision-safe ones. Leave it as written for now.

- [ ] **Step 2: Write the sensor platform**

Replace `custom_components/cellar_tracker/sensor.py` entirely:

```python
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

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .aggregate import items_payload
from .const import DOMAIN, LONG_TAIL, LOW_CARDINALITY
from .coordinator import CellarTrackerCoordinator
from .naming import SLICE_DIMENSIONS, slugify

_LOGGER = logging.getLogger(__name__)


class _Base(CoordinatorEntity[CellarTrackerCoordinator], SensorEntity):
    """Shared availability policy."""

    _attr_should_poll = False

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

    def __init__(self, coordinator, dimension: str, value: str) -> None:
        super().__init__(coordinator)
        self._dimension = dimension
        self._value = value
        self._attr_unique_id = f"{DOMAIN}_{dimension}_{slugify(value)}"
        self._attr_name = f"Cellar Tracker {dimension} {value}"

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
        self._attr_name = f"Cellar Tracker by {dimension}"

    def _items(self):
        return self.coordinator.data.tails.get(self._dimension, [])

    @property
    def native_value(self) -> int:
        return len(self._items())

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {"items": items_payload(self._items())}


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
        "total_bottles", "Cellar Tracker total bottles",
        None, SensorStateClass.MEASUREMENT, "bottles", "mdi:bottle-wine",
    ),
    # monetary requires TOTAL: sensor/const.py maps MONETARY to {TOTAL}
    # only, and measurement logs a warning on every install.
    (
        "total_value", "Cellar Tracker total value",
        SensorDeviceClass.MONETARY, SensorStateClass.TOTAL, CURRENCY, None,
    ),
    # An average is not a total, so it gets no device_class at all.
    (
        "average_value", "Cellar Tracker average value",
        None, SensorStateClass.MEASUREMENT, CURRENCY, "mdi:cash",
    ),
    (
        "average_score", "Cellar Tracker average score",
        None, SensorStateClass.MEASUREMENT, "points", "mdi:star",
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
        for item in coordinator.data.low.get(dimension, []):
            entities.append(CellarValueSensor(coordinator, dimension, item.name))
    for dimension in SLICE_DIMENSIONS:
        entities.append(CellarSliceSensor(coordinator, dimension))
    entities.extend(_scalars(coordinator))
    return entities


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up from discovery only."""
    if discovery_info is None:
        return
    coordinator = hass.data[DOMAIN]
    async_add_entities(build_entities(coordinator))
```

- [ ] **Step 3: Verify lint and types**

Run: `uvx ruff check . && uvx ty check`
Expected: both clean.

- [ ] **Step 4: Add a smoke test for the device/state class pairing**

Home Assistant is installed in the test environment, so the riskiest thing in this task can be checked without a running instance.

`SCALAR_SPECS` is defined in Step 2's code as a module-level tuple of `(key, name, device_class, state_class, unit, icon)`, precisely so these pairings can be inspected without constructing a coordinator.

Create `tests/test_sensor_classes.py`:

```python
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.components.sensor.const import DEVICE_CLASS_STATE_CLASSES

from custom_components.cellar_tracker import sensor


def test_entity_classes_are_importable():
    assert sensor.CellarValueSensor
    assert sensor.CellarSliceSensor
    assert sensor.CellarScalarSensor


def test_every_scalar_uses_a_valid_device_and_state_class_pairing():
    # HA logs a warning per entity for an invalid pairing, and its own code
    # comment says this should raise in a future release.
    for key, _name, device_class, state_class, _unit, _icon in sensor.SCALAR_SPECS:
        if device_class is None:
            continue
        allowed = DEVICE_CLASS_STATE_CLASSES[device_class]
        assert state_class in allowed, (
            f"{key}: {state_class} invalid for {device_class}, allowed: {allowed}"
        )


def test_monetary_requires_total():
    # Pins the specific defect this rewrite exists to fix.
    assert DEVICE_CLASS_STATE_CLASSES[SensorDeviceClass.MONETARY] == {
        SensorStateClass.TOTAL
    }


def test_slice_sensors_exclude_items_from_the_recorder():
    # Without this the recorder blanks the entity's whole attribute dict.
    assert "items" in sensor.CellarSliceSensor._unrecorded_attributes
```

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests/test_sensor_classes.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/cellar_tracker/naming.py custom_components/cellar_tracker/sensor.py tests/test_sensor_classes.py
git commit -m "feat: hybrid entity model with correct device and state classes"
```

---

### Task 8: Slug collision guard

**Files:**
- Modify: `custom_components/cellar_tracker/naming.py`
- Test: `tests/test_slug.py`

`naming.py` has no Home Assistant imports, which is why this test can import it directly.

Two distinct values can slugify to the same string — `Domaine-Leroy` and `Domaine Leroy` both become `domaine_leroy`, as do `Ch. Margaux` / `Ch Margaux` and `A&B Wines` / `A B Wines`. Punctuation is what collides, not accents: `Côtes du Rhône` becomes `c_tes_du_rh_ne`, which is ugly but distinct from `cotes_du_rhone`. Two entities with the same `unique_id` means the second is silently dropped by Home Assistant.

- [ ] **Step 1: Write the failing test**

Create `tests/test_slug.py`:

```python
from custom_components.cellar_tracker.naming import slugify, unique_slugs


def test_slug_basics():
    assert slugify("Côtes du Rhône") == "c_tes_du_rh_ne"
    assert slugify("Red - Fortified") == "red_fortified"
    assert slugify("  spaced  ") == "spaced"


def test_colliding_names_get_distinct_slugs():
    # Punctuation collapses: both of these slugify to domaine_leroy.
    slugs = unique_slugs(["Domaine-Leroy", "Domaine Leroy"])
    assert len(set(slugs.values())) == 2, slugs
    assert set(slugs.values()) == {"domaine_leroy", "domaine_leroy_2"}


def test_accented_names_do_not_collide():
    # Guards the assumption above: accents produce distinct slugs already.
    slugs = unique_slugs(["Cotes du Rhone", "Côtes du Rhône"])
    assert slugs["Cotes du Rhone"] == "cotes_du_rhone"
    assert slugs["Côtes du Rhône"] == "c_tes_du_rh_ne"


def test_stable_order_independent_of_input_order():
    a = unique_slugs(["Zeta", "Alpha"])
    b = unique_slugs(["Alpha", "Zeta"])
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests/test_slug.py -q`
Expected: FAIL with `ImportError: cannot import name 'unique_slugs'`

- [ ] **Step 3: Write the implementation**

Add to `naming.py`, below `slugify`:

```python
def unique_slugs(values: list[str]) -> dict[str, str]:
    """Map each value to a slug, suffixing duplicates so none collide.

    Two distinct values can slugify identically (Cotes du Rhone and Cotes
    du Rhone with accents). A duplicate unique_id means Home Assistant
    silently drops the second entity. Sorting first makes the assignment
    stable regardless of the order CellarTracker returns rows in.
    """
    assigned: dict[str, str] = {}
    seen: dict[str, int] = {}
    for value in sorted(values):
        base = slugify(value)
        count = seen.get(base, 0)
        seen[base] = count + 1
        assigned[value] = base if count == 0 else f"{base}_{count + 1}"
    return assigned
```

Rewrite `expected_unique_ids` in `naming.py` to use it, so it cannot disagree with `build_entities`:

```python
def expected_unique_ids(data: CellarData) -> set[str]:
    ids = {f"{DOMAIN}_by_{dimension}" for dimension in SLICE_DIMENSIONS}
    ids |= {f"{DOMAIN}_{key}" for key in SCALAR_KEYS}
    for dimension in LOW_CARDINALITY:
        items = data.low.get(dimension, [])
        slugs = unique_slugs([item.name for item in items])
        ids |= {f"{DOMAIN}_{dimension}_{slugs[item.name]}" for item in items}
    return ids
```

Then use it in `build_entities` in `sensor.py`:

```python
def build_entities(coordinator) -> list[SensorEntity]:
    entities: list[SensorEntity] = []
    for dimension in LOW_CARDINALITY:
        items = coordinator.data.low.get(dimension, [])
        slugs = unique_slugs([item.name for item in items])
        for item in items:
            entities.append(
                CellarValueSensor(coordinator, dimension, item.name, slugs[item.name])
            )
    for dimension in list(LONG_TAIL) + ["score_band"]:
        entities.append(CellarSliceSensor(coordinator, dimension))
    entities.extend(_scalars(coordinator))
    return entities
```

Change `CellarValueSensor.__init__` to take the slug rather than deriving it:

```python
    def __init__(self, coordinator, dimension: str, value: str, slug: str) -> None:
        super().__init__(coordinator)
        self._dimension = dimension
        self._value = value
        self._attr_unique_id = f"{DOMAIN}_{dimension}_{slug}"
        self._attr_name = f"Cellar Tracker {dimension} {value}"
```

`sensor.py` must now import `unique_slugs` alongside `slugify`:

```python
from .naming import SLICE_DIMENSIONS, unique_slugs
```

`slugify` is no longer called directly from `sensor.py`; remove it from that import if ruff flags it as unused.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests -q`
Expected: PASS, 22 passed.

- [ ] **Step 5: Lint and commit**

```bash
uvx ruff check . && uvx ty check
git add custom_components/cellar_tracker/naming.py custom_components/cellar_tracker/sensor.py tests/test_slug.py
git commit -m "fix: guard against slug collisions producing duplicate unique_ids"
```

---

### Task 9: Registry cleanup

**Files:**
- Create: `custom_components/cellar_tracker/migrate.py`
- Test: `tests/test_migrate.py`

Old entities carry `unique_id`s and no config entry, so Home Assistant writes `unavailable` for every one of them at every start, indefinitely. The 30-day orphan purge only touches entries already marked deleted. Without this, users are left with ~400 grey entities to delete by hand.

**Interfaces:**
- Consumes: `naming.expected_unique_ids`
- Produces: `stale_unique_ids(registered: set[str], expected: set[str]) -> set[str]` (pure, testable) and `async_cleanup_registry(hass, expected) -> int`

`homeassistant` is installed in the test environment, so import it normally at module level.

- [ ] **Step 1: Write the failing test**

Create `tests/test_migrate.py`:

```python
from custom_components.cellar_tracker.migrate import stale_unique_ids


def test_removes_ids_not_in_the_new_model():
    registered = {"cellar_tracker.cellar_tracker.country.france", "cellar_tracker_by_producer"}
    expected = {"cellar_tracker_by_producer"}
    assert stale_unique_ids(registered, expected) == {
        "cellar_tracker.cellar_tracker.country.france"
    }


def test_keeps_everything_when_nothing_is_stale():
    expected = {"cellar_tracker_by_producer", "cellar_tracker_total_value"}
    assert stale_unique_ids(expected, expected) == set()


def test_never_removes_an_expected_id_even_if_registered_has_more():
    registered = {"a", "b", "c"}
    expected = {"b"}
    assert stale_unique_ids(registered, expected) == {"a", "c"}
    assert "b" not in stale_unique_ids(registered, expected)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests/test_migrate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'custom_components.cellar_tracker.migrate'`

- [ ] **Step 3: Write the implementation**

Create `custom_components/cellar_tracker/migrate.py`:

```python
"""Remove entities the old per-value model registered.

Old entities have unique_ids and no config entry, so Home Assistant writes
`unavailable` for each of them at every start, forever -- the 30-day orphan
purge only applies to entries already marked deleted. Left alone, upgrading
users inherit roughly 400 grey entities to delete by hand.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def stale_unique_ids(registered: set[str], expected: set[str]) -> set[str]:
    """Registered IDs the new model no longer provides."""
    return registered - expected


async def async_cleanup_registry(hass: HomeAssistant, expected: set[str]) -> int:
    """Delete this platform's registry entries that are no longer provided.

    Returns the number removed.
    """
    registry = er.async_get(hass)
    ours = {
        entry.unique_id: entry.entity_id
        for entry in registry.entities.values()
        if entry.platform == DOMAIN
    }
    stale = stale_unique_ids(set(ours), expected)
    for unique_id in stale:
        registry.async_remove(ours[unique_id])
    if stale:
        _LOGGER.info(
            "Removed %s Cellar Tracker entities left over from the previous "
            "sensor model", len(stale),
        )
    return len(stale)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests -q`
Expected: PASS, 25 passed.

- [ ] **Step 5: Lint and commit**

```bash
uvx ruff check . && uvx ty check
git add custom_components/cellar_tracker/migrate.py tests/test_migrate.py
git commit -m "feat: remove registry entries orphaned by the old sensor model"
```

---

### Task 10: Wire up setup

**Files:**
- Rewrite: `custom_components/cellar_tracker/__init__.py`
- Modify: `custom_components/cellar_tracker/manifest.json`
- Modify: `hacs.json`

- [ ] **Step 1: Write the implementation**

Replace `custom_components/cellar_tracker/__init__.py` entirely. Note this converts `setup` to `async_setup`, so the blocking first fetch no longer stalls Home Assistant startup.

```python
"""Cellar Tracker integration.

YAML-configured, so there is no config entry and therefore no device. See
docs/superpowers/specs/2026-09-14-cellar-tracker-dashboard-design.md.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery as hdisco
from homeassistant.helpers.typing import ConfigType

from .const import DEFAULT_SCORE_BANDS, DOMAIN
from .coordinator import CellarTrackerCoordinator
from .migrate import async_cleanup_registry
from .naming import expected_unique_ids

_LOGGER = logging.getLogger(__name__)

MIN_SCAN_INTERVAL = 30
DEFAULT_SCAN_INTERVAL = 3600

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
    """Set up Cellar Tracker from YAML."""
    conf = config[DOMAIN]
    seconds = conf[CONF_SCAN_INTERVAL]
    _LOGGER.debug("Using scan_interval of %s seconds", seconds)

    coordinator = CellarTrackerCoordinator(
        hass,
        conf[CONF_USERNAME],
        conf[CONF_PASSWORD],
        timedelta(seconds=seconds),
        DEFAULT_SCORE_BANDS,
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN] = coordinator

    await async_cleanup_registry(hass, expected_unique_ids(coordinator.data))

    hass.async_create_task(
        hdisco.async_load_platform(hass, "sensor", DOMAIN, {}, config)
    )
    return True
```

- [ ] **Step 2: Bump the manifest and declare the HA floor**

`custom_components/cellar_tracker/manifest.json` — set `"version": "20260914"`.

`hacs.json` — add `"homeassistant": "2024.6.0"`:

```json
{
  "name": "Cellar Tracker -- Wine Collection Management",
  "render_readme": true,
  "domain": "cellar_tracker",
  "homeassistant": "2024.6.0",
  "documentation": "https://github.com/ahoernecke/ha_cellar_tracker",
  "issue_tracker": "https://github.com/ahoernecke/ha_cellar_tracker/issues"
}
```

- [ ] **Step 3: Verify both JSON files parse**

```bash
python3 -c "import json; json.load(open('hacs.json')); json.load(open('custom_components/cellar_tracker/manifest.json')); print('both valid')"
```
Expected: `both valid`

- [ ] **Step 4: Run the full suite and lint**

Run: `uv run --with homeassistant --with pytest --with pandas pytest tests -q && uvx ruff check . && uvx ty check`
Expected: 25 passed, both linters clean.

- [ ] **Step 5: Commit**

```bash
git add custom_components/cellar_tracker/__init__.py custom_components/cellar_tracker/manifest.json hacs.json
git commit -m "feat: wire coordinator into async setup with registry cleanup"
```

---

### Task 11: Load it in a real Home Assistant

The first ten tasks are verified by unit tests and linters. None of them prove the integration loads. This task does.

**Files:** none changed unless a defect is found.

- [ ] **Step 1: Deploy**

```bash
cp -r custom_components/cellar_tracker /path/to/homeassistant/config/custom_components/
```

Add to that instance's `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.cellar_tracker: debug

cellar_tracker:
  username: !secret cellar_tracker_username
  password: !secret cellar_tracker_password
  scan_interval: 3600
```

Restart Home Assistant.

- [ ] **Step 2: Confirm the entity set**

In Developer Tools → States, filter on `cellar_tracker`. Expected: **47 entities** — 34 per-value, 9 slice, 4 scalar.

Check specifically:
- `sensor.cellar_tracker_country_france` has a numeric state and unit `bottles`
- `sensor.cellar_tracker_by_producer` has a numeric state and an `items` attribute that is a list of dicts
- `sensor.cellar_tracker_total_value` has a numeric state, unit `DKK`, `device_class: monetary`, `state_class: total`

- [ ] **Step 3: Check the log for the three failure modes this plan exists to prevent**

```
grep -iE "monetary|state class|not JSON serializable|numpy|Attributes.*exceed|16384" home-assistant.log
```

Expected: **no matches**. Any hit is a task failure:
- a `state class` warning means Task 7's device/state class pairing is wrong
- `not JSON serializable` means Task 3's native casting missed a path
- an attribute-size warning means Task 5's budget is not actually being honoured

- [ ] **Step 4: Confirm the registry cleanup ran**

```
grep "left over from the previous sensor model" home-assistant.log
```

Expected on an instance that ran the old version: one line naming the count. On a fresh install: no line, which is correct.

Then confirm no `unavailable` `cellar_tracker` entities remain in the registry.

- [ ] **Step 5: Confirm statistics compile**

Wait for two refreshes, then check Developer Tools → Statistics for `sensor.cellar_tracker_total_value`. It must appear. If it does not, the device/state class pairing is still wrong.

- [ ] **Step 6: Commit any fixes**

If defects were found, fix them, re-run `uv run --with homeassistant --with pytest --with pandas pytest tests -q`, and commit with a message naming what the live load caught.

---

### Task 12: Dashboard YAML

**Files:**
- Create: `docs/dashboard/overview.yaml`
- Create: `docs/dashboard/explore.yaml`

Requires mushroom, flex-table-card and card-mod installed via HACS.

- [ ] **Step 1: Write the Overview view**

Create `docs/dashboard/overview.yaml`:

```yaml
title: Overview
path: overview
cards:
  - type: custom:mushroom-chips-card
    chips:
      - type: entity
        entity: sensor.cellar_tracker_total_bottles
        icon: mdi:bottle-wine
      - type: entity
        entity: sensor.cellar_tracker_total_value
        icon: mdi:cash
      - type: entity
        entity: sensor.cellar_tracker_average_score
        icon: mdi:star
      - type: entity
        entity: sensor.cellar_tracker_by_producer
        icon: mdi:account-group

  - type: statistics-graph
    title: Cellar value
    entities:
      - sensor.cellar_tracker_total_value
    stat_types:
      - state
    days_to_show: 365
    period: day
```

`stat_types: [state]` is required: `total` produces `state`/`sum` statistics, not `mean`.

- [ ] **Step 2: Write the Explore view**

Create `docs/dashboard/explore.yaml`. One card per long-tail dimension; `sort_by` is set at config time.

```yaml
title: Explore
path: explore
cards:
  - type: custom:flex-table-card
    title: By producer
    entities:
      include: sensor.cellar_tracker_by_producer
    max_rows: 50
    sort_by: count-
    columns:
      - name: Producer
        id: name
        data: items.name
      - name: Bottles
        id: count
        data: items.count
      - name: Avg value
        id: value_avg
        data: items.value_avg
        modify: parseFloat(x).toFixed(0)
      - name: Avg score
        id: score_avg
        data: items.score_avg
        modify: x === null ? '-' : parseFloat(x).toFixed(1)

  - type: custom:flex-table-card
    title: By region
    entities:
      include: sensor.cellar_tracker_by_region
    sort_by: count-
    columns:
      - name: Region
        id: name
        data: items.name
      - name: Bottles
        id: count
        data: items.count
      - name: Avg value
        id: value_avg
        data: items.value_avg
        modify: parseFloat(x).toFixed(0)
      - name: Avg score
        id: score_avg
        data: items.score_avg
        modify: x === null ? '-' : parseFloat(x).toFixed(1)

  - type: custom:flex-table-card
    title: By score band
    entities:
      include: sensor.cellar_tracker_by_score_band
    sort_by: name+
    columns:
      - name: Band
        id: name
        data: items.name
      - name: Bottles
        id: count
        data: items.count
      - name: Avg value
        id: value_avg
        data: items.value_avg
        modify: parseFloat(x).toFixed(0)
```

Explicit column `id`s are required: with list-of-dict expansion, `sort_by` needs them.

- [ ] **Step 3: Load both views in the real instance**

Paste each into a new dashboard via raw config editor. Confirm the producer table renders 50 rows with real names, and that score columns show `-` rather than `null` where a group has no score.

- [ ] **Step 4: Commit**

```bash
git add docs/dashboard/overview.yaml docs/dashboard/explore.yaml
git commit -m "docs: add dashboard YAML for overview and explore views"
```

---

### Task 13: README and CLAUDE.md

**Files:**
- Rewrite: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Rewrite the README**

Replace the Configuration and Dashboard sections. Required content:

- **Breaking-change notice at the top of the dashboard section**, stating that entity IDs changed, that old dashboard cards will not work, and that obsolete entities are removed automatically on first start after upgrade.
- **Requirements** updated: mushroom, flex-table-card, card-mod. Remove any implication that `auto-entities` or `apexcharts-card` is needed.
- **Dashboard section** replaced with the contents of `docs/dashboard/overview.yaml` and `docs/dashboard/explore.yaml`. Delete every old flex-table snippet — do not leave them alongside the new ones.
- A short **Entities** table: 34 per-value sensors, 9 slice sensors, 4 scalars, with one example entity ID of each shape and a note that slice breakdowns live in the `items` attribute.

- [ ] **Step 2: Correct CLAUDE.md**

The **Double throttling** paragraph is now wrong — there is no double `Throttle`. Replace it with:

```markdown
**One coordinator, not two throttles.** `CellarTrackerCoordinator` (`coordinator.py`) owns fetching on `scan_interval`; entities are `CoordinatorEntity` with `should_poll = False`. The previous design applied `Throttle` to both the hub and every entity, and because `Throttle` only stamps its timestamp on success, a failing fetch was retried by every entity on every poll.

**Availability is deliberately stale-tolerant.** `CoordinatorEntity.available` defaults to `coordinator.last_update_success`, which blanks every entity after one failed refresh. `_Base.available` overrides it to `coordinator.ever_succeeded`, so a CellarTracker outage shows yesterday's inventory instead of nothing.
```

Also update the **Architecture** section: the data dict contract is now `CellarData` from `aggregate.py`, and the entity-naming paragraph's warning now describes the *new* scheme.

Add to the Commands section:

```markdown
uv run --with homeassistant --with pytest --with pandas pytest tests -q   # tests
```

- [ ] **Step 3: Verify the README has no stale references**

```bash
grep -niE "auto-entities|apexcharts|sankey|cellar_tracker_country\*|cellar_tracker_producer\*" README.md
```
Expected: no matches.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: rewrite README for new entity model and correct CLAUDE.md"
```

---

## Self-Review

**Spec coverage:** Hybrid entity model → Tasks 7, 8. `monetary`+`total` → Task 7. Payload budget and `_unrecorded_attributes` → Tasks 5, 7. Native type casting → Tasks 3, 5. `SensorEntity`+`DataUpdateCoordinator` → Tasks 6, 7, 10. Availability override → Tasks 6, 7. `unique_id`/`name` rules → Tasks 7, 8. Registry cleanup → Task 9. HA version floor → Task 10. Pure `aggregate.py` → Task 3. Error handling (coercion, sentinels, currency) → Tasks 3, 4. Testing → Tasks 1–5, 8, 9. Dashboard → Task 12. Breaking changes and docs → Tasks 10, 13. Composition view and drinking windows are Out of Scope in the spec and correctly absent here.

**Known deviation from the spec:** the spec proposed `_attr_has_entity_name = True`. This plan sets `_attr_name` directly instead, because without a config entry there is no device for `has_entity_name` to be relative to, and explicit names give predictable entity IDs. Task 7 documents this inline.

**Added beyond the spec:** Task 8 (slug collisions). Two distinct values can slugify identically — punctuation collapses, so `Domaine-Leroy` and `Domaine Leroy` both become `domaine_leroy` — producing duplicate `unique_id`s and a silently dropped entity. The spec did not consider it.

**Type consistency:** `GroupItem(name, count, value_avg, score_avg)` is used identically in Tasks 3, 4, 5, 7. `items_payload` is defined in Task 5 and consumed in Task 7. `expected_unique_ids` is defined in Task 7 and consumed in Tasks 9, 10. `unique_slugs` is defined in Task 8 and used in both `build_entities` and `expected_unique_ids`, so the two cannot disagree. `coordinator.ever_succeeded` is defined in Task 6 and used in Task 7.
