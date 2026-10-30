import pytest

from meridian.geo import names, taxonomy


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("São Paulo", "sao paulo"),
        ("Zürich", "zurich"),
        ("St. Louis", "saint louis"),
        ("Mt. Everest", "mount everest"),
        ("Coeur d'Alene", "coeur dalene"),
        ("Stratford-upon-Avon", "stratford upon avon"),
        ("  Rotterdam  ", "rotterdam"),
        ("ＮＥＷ　ＹＯＲＫ", "new york"),
        ("Москва", "москва"),
        ("Іван", "іван"),
        ("東京", "東京"),
        ("", ""),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert names.normalize_name(raw) == expected


def test_cyrillic_marks_are_stripped_but_devanagari_kept() -> None:
    assert names.normalize_name("Й") == names.normalize_name("И")
    assert names.normalize_name("दिल्ली") == "दिल्ली"


def test_strip_prefix_and_keys() -> None:
    assert names.strip_prefix("port of rotterdam") == "rotterdam"
    assert names.strip_prefix("rotterdam") is None
    assert names.name_keys("Port of Rotterdam") == ["port of rotterdam", "rotterdam"]
    assert "moskva" in names.name_keys("Москва")


def test_transliteration() -> None:
    assert names.transliterate("Köln") == "koln"
    assert names.transliterate("Київ") == "kiyiv"


def test_settlement_type_thresholds() -> None:
    assert taxonomy.settlement_type(2_000_000) == "city"
    assert taxonomy.settlement_type(50_000) == "town"
    assert taxonomy.settlement_type(900) == "village"
    assert taxonomy.settlement_type(None, fallback="town") == "town"
    assert taxonomy.settlement_type(500, capital=True) == "city"


def test_geonames_type_mapping() -> None:
    assert taxonomy.geonames_type("S", "AIRP", 0) == "airport"
    assert taxonomy.geonames_type("A", "ADM1", 0) == "admin1"
    assert taxonomy.geonames_type("P", "PPLH", 5000) is None
    assert taxonomy.geonames_type("P", "PPL", 250_000) == "city"
    assert taxonomy.geonames_type("T", "MT", 0) is None
