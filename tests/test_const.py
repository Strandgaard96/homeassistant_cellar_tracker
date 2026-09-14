from itertools import pairwise

from custom_components.cellar_tracker import const


def test_dimension_sets_are_disjoint():
    assert not (set(const.LOW_CARDINALITY) & set(const.LONG_TAIL))


def test_expected_dimension_counts():
    assert len(const.LOW_CARDINALITY) == 6
    assert len(const.LONG_TAIL) == 8


def test_score_bands_are_contiguous_and_cover_everything():
    bands = const.DEFAULT_SCORE_BANDS
    assert bands[0][0] is None, "first band must be open-ended below"
    assert bands[-1][1] is None, "last band must be open-ended above"
    for (_, upper, _), (lower, _, _) in pairwise(bands):
        assert upper == lower, f"gap or overlap between {upper} and {lower}"
