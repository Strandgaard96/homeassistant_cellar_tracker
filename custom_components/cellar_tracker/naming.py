"""Entity identity: slugs, unique IDs, and the set of IDs we provide.

Imports no Home Assistant module so it can be tested with plain pytest.
"""

from __future__ import annotations

import re

from .aggregate import CellarData
from .const import DOMAIN, LONG_TAIL, LOW_CARDINALITY

SCALAR_KEYS = ("total_bottles", "total_value", "average_value", "average_score")
SLICE_DIMENSIONS = (*LONG_TAIL, "score_band")

UNNAMED = "unnamed"


def slugify(value: str) -> str:
    """Lowercase and collapse anything non-alphanumeric to a single _.

    Falls back to UNNAMED when nothing sluggable remains (e.g. "---" or an
    emoji-only value) so we never build a malformed unique_id like
    `cellar_tracker_location_`.
    """
    slug = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")
    return slug or UNNAMED


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


def expected_unique_ids(data: CellarData) -> set[str]:
    """Unique IDs the new model produces. Task 9 removes everything else."""
    ids = {f"{DOMAIN}_by_{dimension}" for dimension in SLICE_DIMENSIONS}
    ids |= {f"{DOMAIN}_{key}" for key in SCALAR_KEYS}
    for dimension in LOW_CARDINALITY:
        items = data.low.get(dimension, [])
        slugs = unique_slugs([item.name for item in items])
        ids |= {f"{DOMAIN}_{dimension}_{slugs[item.name]}" for item in items}
    return ids
