"""Features of a (mention, candidate place) pair for the context re-ranker."""

from __future__ import annotations

import math

from meridian.geo import taxonomy
from meridian.geo.names import normalize_name
from meridian.linking.context import ArticleContext, CountryIndex, haversine_km, qualifier_after
from meridian.linking.types import PlaceRecord

FEATURE_NAMES = [
    "bela_score",
    "bela_rank_inverse",
    "bela_listed",
    "name_exact",
    "name_primary",
    "name_similarity",
    "log_population",
    "type_settlement",
    "type_admin",
    "type_facility",
    "type_natural",
    "log_uncertainty",
    "country_named_in_article",
    "outlet_country_match",
    "qualifier_match",
    "same_country_share",
    "same_admin1_share",
    "log_distance_to_cluster",
    "has_cluster",
    "facility_word_agrees",
    "article_language_alias",
]

_FACILITY_WORDS = (
    "port",
    "airport",
    "terminal",
    "refinery",
    "plant",
    "factory",
    "station",
    "dam",
    "bridge",
    "tunnel",
    "hospital",
    "stadium",
    "base",
    "puerto",
    "aeropuerto",
    "hafen",
    "flughafen",
    "porto",
    "aeroporto",
)


def type_group(place_type: str) -> str:
    if place_type in taxonomy.FACILITY_TYPES:
        return "facility"
    if place_type in taxonomy.SETTLEMENT_TYPES:
        return "settlement"
    if place_type in taxonomy.ADMIN_TYPES:
        return "admin"
    return "natural"


def pair_features(
    surface: str,
    start: int,
    end: int,
    place: PlaceRecord,
    *,
    context: ArticleContext,
    countries: CountryIndex,
    bela_score: float = 0.0,
    bela_rank: int | None = None,
    name_similarity: float = 0.0,
    matched_primary: bool = False,
    alias_in_article_language: bool = False,
) -> dict[str, float]:
    normalized = normalize_name(surface)
    group = type_group(place.type)
    qualifier = qualifier_after(context.text, end)
    region = normalize_name(place.admin1_name or "")
    country_name = countries.by_code.get(place.country_code or "", "")
    qualifier_hit = bool(qualifier and qualifier in (region, country_name, (place.country_code or "").lower()))
    others = [p for p in context.resolved if p.place_id != place.place_id]
    same_country = sum(1 for p in others if p.country_code and p.country_code == place.country_code)
    same_admin1 = sum(1 for p in others if p.admin1_name and p.admin1_name == place.admin1_name)
    centroid = context.centroid(place.place_id)
    distance = haversine_km(place.lat, place.lon, centroid[0], centroid[1]) if centroid else -1.0
    sentence_window = context.text[max(0, start - 40) : start].lower().split()
    facility_word = any(w in _FACILITY_WORDS for w in sentence_window[-3:]) or any(
        w in normalized.split() for w in _FACILITY_WORDS
    )
    return {
        "bela_score": bela_score,
        "bela_rank_inverse": 1.0 / (1 + bela_rank) if bela_rank is not None else 0.0,
        "bela_listed": 1.0 if bela_rank is not None else 0.0,
        "name_exact": 1.0 if name_similarity >= 0.999 else 0.0,
        "name_primary": 1.0 if matched_primary else 0.0,
        "name_similarity": name_similarity,
        "log_population": math.log1p(place.population or 0),
        "type_settlement": float(group == "settlement"),
        "type_admin": float(group == "admin"),
        "type_facility": float(group == "facility"),
        "type_natural": float(group == "natural"),
        "log_uncertainty": math.log1p(place.uncertainty_km or 0),
        "country_named_in_article": 1.0 if place.country_code in context.named_countries else 0.0,
        "outlet_country_match": 1.0 if context.outlet_country and place.country_code == context.outlet_country else 0.0,
        "qualifier_match": 1.0 if qualifier_hit else 0.0,
        "same_country_share": same_country / len(others) if others else 0.0,
        "same_admin1_share": same_admin1 / len(others) if others else 0.0,
        "log_distance_to_cluster": math.log1p(distance) if distance >= 0 else 0.0,
        "has_cluster": 1.0 if centroid else 0.0,
        "facility_word_agrees": 1.0
        if (facility_word and group == "facility") or (not facility_word and group != "facility")
        else 0.0,
        "article_language_alias": 1.0 if alias_in_article_language else 0.0,
    }


def to_vector(features: dict[str, float]) -> list[float]:
    return [features[name] for name in FEATURE_NAMES]
