"""Place type taxonomy, GeoNames mappings, and default uncertainty rules."""

from __future__ import annotations

FACILITY_TYPES = (
    "airport",
    "seaport",
    "railway_station",
    "power_station",
    "refinery",
    "factory",
    "dam",
    "bridge",
    "tunnel",
    "border_crossing",
    "military_base",
    "hospital",
    "stadium",
)
SETTLEMENT_TYPES = ("city", "town", "village")
ADMIN_TYPES = ("country", "admin1", "admin2", "admin_region")
NATURAL_TYPES = ("river", "lake", "island", "mountain")
PLACE_TYPES = FACILITY_TYPES + SETTLEMENT_TYPES + ADMIN_TYPES + NATURAL_TYPES

LOCATION_LEVELS = ("facility", "city", "admin2", "admin1", "country", "natural")

# GeoNames feature "class.code" to place type. Codes were checked against featureCodes_en.txt.
GEONAMES_FEATURES: dict[str, str] = {
    "A.PCLI": "country",
    "A.PCLD": "country",
    "A.PCLF": "country",
    "A.PCLS": "country",
    "A.PCL": "country",
    "A.ADM1": "admin1",
    "A.ADM2": "admin2",
    "S.AIRP": "airport",
    "S.AIRF": "airport",
    "S.AIRB": "military_base",
    "S.BRKS": "military_base",
    "S.MILB": "military_base",
    "S.PRT": "seaport",
    "S.HBR": "seaport",
    "S.RSTN": "railway_station",
    "S.PS": "power_station",
    "S.PSH": "power_station",
    "S.PSN": "power_station",
    "S.OILR": "refinery",
    "S.MFG": "factory",
    "S.DAM": "dam",
    "S.BDG": "bridge",
    "S.TNL": "tunnel",
    "S.PSTB": "border_crossing",
    "S.HSP": "hospital",
    "S.STDM": "stadium",
}
# Populated place codes that are kept (historic, destroyed, abandoned, and sections are not).
GEONAMES_SETTLEMENT_CODES = frozenset(
    {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC", "PPLCD", "PPLG", "PPLS", "PPLF", "PPLL", "PPLR"}
)
CAPITAL_CODES = frozenset({"PPLC", "PPLCD"})

# GeoNames lists tens of thousands of minor dams, bridges, and tunnels with no importance signal.
# They are skipped by default; notable ones come from Wikidata, which has sitelinks.
MINOR_FACILITY_TYPES = frozenset({"dam", "bridge", "tunnel"})

CITY_MIN_POPULATION = 100_000
TOWN_MIN_POPULATION = 10_000
LARGE_CITY_POPULATION = 1_000_000

# Alias kinds kept from GeoNames alternate names besides real languages.
ALIAS_CODE_LANGUAGES = {"iata": "iata", "icao": "icao", "abbr": "abbr"}

# (place_type, min_population, uncertainty_km, location_level, polygon_based, country_level)
DEFAULT_UNCERTAINTY_RULES: list[tuple[str, int, float, str, bool, bool]] = [
    *((t, 0, 2.0, "facility", False, False) for t in FACILITY_TYPES),
    ("village", 0, 5.0, "city", False, False),
    ("town", 0, 10.0, "city", False, False),
    ("city", 0, 25.0, "city", False, False),
    ("city", LARGE_CITY_POPULATION, 40.0, "city", False, False),
    ("admin2", 0, 30.0, "admin2", True, False),
    ("admin_region", 0, 30.0, "admin2", True, False),
    ("admin1", 0, 100.0, "admin1", True, False),
    ("country", 0, 300.0, "country", True, True),
    ("river", 0, 25.0, "natural", False, False),
    ("lake", 0, 10.0, "natural", False, False),
    ("island", 0, 15.0, "natural", False, False),
    ("mountain", 0, 10.0, "natural", False, False),
]


def settlement_type(population: int | None, fallback: str = "village", capital: bool = False) -> str:
    """Classify a settlement by population, which is consistent across sources."""
    if capital:
        return "city"
    if population is None or population <= 0:
        return fallback if fallback in SETTLEMENT_TYPES else "village"
    if population >= CITY_MIN_POPULATION:
        return "city"
    if population >= TOWN_MIN_POPULATION:
        return "town"
    return "village"


def geonames_type(feature_class: str, feature_code: str, population: int) -> str | None:
    """Map a GeoNames record to a place type, or None when it is out of scope."""
    mapped = GEONAMES_FEATURES.get(f"{feature_class}.{feature_code}")
    if mapped:
        return mapped
    if feature_class == "P" and feature_code in GEONAMES_SETTLEMENT_CODES:
        return settlement_type(population, capital=feature_code in CAPITAL_CODES)
    return None
