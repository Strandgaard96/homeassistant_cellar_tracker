"""Entity identity: slugs, unique IDs, and the set of IDs we provide.

Imports no Home Assistant module so it can be tested with plain pytest.
"""

from __future__ import annotations

import re

from .aggregate import CellarData
from .const import DOMAIN, LONG_TAIL, LOW_CARDINALITY

SCALAR_KEYS = ("total_bottles", "total_value", "average_value", "average_score")
SLICE_DIMENSIONS = (*LONG_TAIL, "score_band")


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
