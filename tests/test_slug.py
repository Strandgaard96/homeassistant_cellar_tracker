from custom_components.cellar_tracker.naming import UNNAMED, slugify, unique_slugs


def test_slug_basics():
    assert slugify("Côtes du Rhône") == "c_tes_du_rh_ne"
    assert slugify("Red - Fortified") == "red_fortified"
    assert slugify("  spaced  ") == "spaced"
    # Never empty: Location is user-defined, and an empty slug would build a
    # malformed unique_id like `cellar_tracker_location_`.
    assert slugify("---") == "unnamed"
    assert slugify("🍷") == "unnamed"


def test_colliding_names_get_distinct_slugs():
    # Punctuation collapses: both of these slugify to domaine_leroy.
    slugs = unique_slugs(["Domaine-Leroy", "Domaine Leroy"])
    assert len(set(slugs.values())) == 2, slugs
    assert set(slugs.values()) == {"domaine_leroy", "domaine_leroy_2"}
    # Two unsluggable names must still get distinct, well-formed ids.
    assert set(unique_slugs(["---", "###"]).values()) == {UNNAMED, f"{UNNAMED}_2"}
    # A generated suffix must not collide with another value's natural slug.
    three = unique_slugs(["Wine Room", "Wine-Room", "Wine Room 2"])
    assert len(set(three.values())) == 3, three


def test_accented_names_do_not_collide():
    # Guards the assumption above: accents produce distinct slugs already.
    slugs = unique_slugs(["Cotes du Rhone", "Côtes du Rhône"])
    assert slugs["Cotes du Rhone"] == "cotes_du_rhone"
    assert slugs["Côtes du Rhône"] == "c_tes_du_rh_ne"


def test_stable_order_independent_of_input_order():
    a = unique_slugs(["Zeta", "Alpha"])
    b = unique_slugs(["Alpha", "Zeta"])
    assert a == b
