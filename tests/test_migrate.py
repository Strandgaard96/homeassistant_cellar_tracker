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
