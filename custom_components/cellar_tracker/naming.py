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
    """Map each value to a slug, disambiguating duplicates so none collide.

    Two distinct values can slugify identically (punctuation collapses:
    "Domaine-Leroy" and "Domaine Leroy" both give "domaine_leroy"). A
    duplicate unique_id makes Home Assistant silently drop the second entity.

    A generated suffix must also not collide with some OTHER value's natural
    slug: given "Wine Room", "Wine-Room" and a real location literally named
    "Wine Room 2", a naive counter hands "wine_room_2" to two different
    values. Hence the `natural` check below.

    Sorting makes the assignment independent of the order CellarTracker
    returns rows in. Adding an unrelated value never moves an existing slug.

    Known limitation, accepted: when a collision appears for the FIRST time,
    the incumbent that previously held the bare slug moves to a suffixed one,
    so its unique_id changes once and the registry cleanup removes the stale
    entry. Unavoidable without suffixing every entity unconditionally, which
    would make all 47 ids unreadable.
    """
    bases = {value: slugify(value) for value in values}
    natural = set(bases.values())
    assigned: dict[str, str] = {}
    used: set[str] = set()
    for value in sorted(values):
        base = bases[value]
        candidate, suffix = base, 1
        while candidate in used or (suffix > 1 and candidate in natural):
            suffix += 1
            candidate = f"{base}_{suffix}"
        assigned[value] = candidate
        used.add(candidate)
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
