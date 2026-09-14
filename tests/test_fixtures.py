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
