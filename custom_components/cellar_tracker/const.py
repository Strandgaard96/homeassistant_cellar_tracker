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

# Recorder discards an entity's whole attribute dict above 16384 bytes
# (recorder/db_schema.py:90). Budget 12 KiB for margin.
MAX_ATTR_BYTES = 12288

# All 184 producers serialise to 17112 bytes, over the hard cap. The
# Explore card renders 50 rows, so 100 is already double what is shown.
ITEMS_LIMIT = 100
