from meridian.etl import embeddings, merge
from meridian.etl.render_report import pct


def compatible(a: str, b: str) -> bool:
    return merge.COMPATIBILITY_GROUP[merge.FAMILY[a]] == merge.COMPATIBILITY_GROUP[merge.FAMILY[b]]


def test_municipality_and_village_are_compatible_but_airport_and_village_are_not() -> None:
    assert compatible("admin_region", "village")
    assert compatible("city", "admin2")
    assert not compatible("airport", "village")
    assert not compatible("river", "city")


def test_every_place_type_has_threshold_and_family() -> None:
    from meridian.geo import taxonomy

    for place_type in taxonomy.PLACE_TYPES:
        assert place_type in merge.MATCH_THRESHOLD_KM
        assert place_type in merge.FAMILY


def test_embedding_texts_carry_location_context() -> None:
    assert embeddings.name_text("Springfield", "city", "Illinois", "United States") == (
        "Springfield (city), Illinois, United States"
    )
    assert embeddings.name_text("Port of Rotterdam", "seaport", None, "Netherlands") == (
        "Port of Rotterdam (seaport), Netherlands"
    )
    assert embeddings.name_text("Heathrow", "railway_station", None, None) == "Heathrow (railway station)"
    assert embeddings.description_text("Springfield", "capital of Illinois") == "Springfield: capital of Illinois"
    assert embeddings.vector_literal([0.5, 0.25]) == "[0.5,0.25]"


def test_percent_formatting() -> None:
    assert pct(0.8764) == "87.6%"
    assert pct(None) == "n/a"
