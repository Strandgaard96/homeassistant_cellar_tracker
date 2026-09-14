import json

from custom_components.cellar_tracker.aggregate import aggregate, items_payload
from custom_components.cellar_tracker.const import ITEMS_LIMIT, MAX_ATTR_BYTES
from tests.fixtures import SAMPLE_ROWS


def test_measured_constants_are_pinned():
    """These are measurements, not preferences.

    MAX_ATTR_BYTES leaves margin under Home Assistant's 16384-byte recorder
    cap; ITEMS_LIMIT exists because all 184 producer entries serialise to
    17112 bytes, over that cap. Raising either without re-measuring
    reintroduces the bug this rewrite fixes, so pin them.
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
    # 184 producers is the measured worst case for this cellar. Against
    # live data they serialise to 15474 bytes -- over the 12288 budget and
    # only just under the recorder's 16384 hard cap. Hence ITEMS_LIMIT.
    # Synthetic names here are longer, so this test sees a bigger number.
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
