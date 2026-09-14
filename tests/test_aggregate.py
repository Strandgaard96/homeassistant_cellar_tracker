import pytest
from custom_components.cellar_tracker.aggregate import CellarData, aggregate
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


def test_vintage_1001_is_relabelled_nv(data):
    labels = [item.name for item in data.tails["vintage"]]
    assert "NV" in labels
    assert "1001" not in labels


def test_blank_valuation_is_excluded_from_totals(data):
    # Row 4 has Valuation="". Five bottles, four priced: 100+200+300+400.
    # Note a blank already coerces to NaN under to_numeric's DEFAULT, so this
    # alone does not prove errors="coerce" is present. The next test does.
    assert data.total_value == 1000.0
    assert data.average_value == 250.0


def test_junk_numeric_cell_does_not_kill_the_update():
    """This is the test that actually pins errors="coerce".

    Measured: pd.to_numeric("") returns NaN even with the default
    errors="raise", but "N/A" raises ValueError. CellarTracker can emit
    "N/A", and under the old code one such cell took down every sensor.
    Delete errors="coerce" from aggregate.py and this test fails; delete it
    and ONLY the blank-cell test above still passes.
    """
    rows = [
        {"iWine": "1", "Country": "Spain", "Valuation": "10.0",
         "CT": "90.0", "Currency": "DKK"},
        {"iWine": "2", "Country": "Spain", "Valuation": "N/A",
         "CT": "not a score", "Currency": "DKK"},
    ]
    result = aggregate(rows)
    assert result.total_bottles == 2
    assert result.total_value == 10.0
    assert result.low["country"][0].count == 2


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
