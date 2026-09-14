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
