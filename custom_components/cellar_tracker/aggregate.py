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
                count=len(chunk),
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
    data.total_bottles = len(df)

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


__all__ = ["COUNT_COLUMN", "NV_LABEL", "NV_SENTINEL", "CellarData", "GroupItem", "aggregate"]
