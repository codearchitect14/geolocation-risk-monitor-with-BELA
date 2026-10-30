from meridian.geo.search import score


def test_exact_larger_place_outranks_small_namesake() -> None:
    big = score(1.0, True, 2_000_000, "city")
    small = score(1.0, True, 800, "village")
    assert big > small


def test_exact_beats_fuzzy_at_equal_population() -> None:
    assert score(1.0, True, 10_000, "town") > score(0.8, False, 10_000, "town")


def test_country_hint_adds_a_bonus() -> None:
    assert score(1.0, True, 10_000, "town", country_match=True) > score(1.0, True, 10_000, "town")
