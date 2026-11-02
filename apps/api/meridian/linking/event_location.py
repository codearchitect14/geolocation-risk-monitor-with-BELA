"""Select the event location from the places resolved in an article (problem C).

The selector is rule based: a weighted score of position (headline, lead), preposition cues, place specificity,
repetition, and consistency with the other places in the text. A learned model can replace it when an event gold
set exists (the features are returned for that purpose); until then the weights below are the shipped method and
are documented in docs/model_card.md. The result carries an uncertainty radius and a level, and a country-level
result is flagged so it is never matched against site assets.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import psycopg

from meridian.linking.context import haversine_km
from meridian.linking.types import MentionResult, PlaceRecord

# Words that introduce the place where something happened, in the languages the harvester covers.
LOCATION_CUES = {
    "in",
    "near",
    "at",
    "outside",
    "around",
    "inside",
    "off",
    "across",
    "within",
    "en",
    "cerca",
    "dans",
    "près",
    "à",
    "bei",
    "nahe",
    "perto",
    "em",
    "no",
    "na",
    "vicino",
    "a",
}
SPECIFICITY = {"facility": 5, "city": 4, "admin2": 3, "admin1": 2, "country": 1, "natural": 3}
WEIGHTS = {
    "headline": 2.0,
    "lead": 1.0,
    "cue": 1.0,
    "specificity": 0.45,
    "count": 0.35,
    "consistent": 0.8,
    "first": 0.5,
}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


@dataclass
class PlaceEvidence:
    place: PlaceRecord
    mentions: int = 0
    first_start: int = 10**9
    in_headline: bool = False
    in_lead: bool = False
    cue: bool = False
    consistent_with: int = 0
    score: float = 0.0
    features: dict[str, float] = field(default_factory=dict)


@dataclass
class EventLocation:
    place: PlaceRecord
    lat: float
    lon: float
    uncertainty_km: float
    level: str
    country_level: bool
    confidence: float
    evidence: list[PlaceEvidence]
    widened: bool = False


def has_cue(text: str, start: int) -> bool:
    words = _WORD.findall(text[max(0, start - 24) : start].lower())
    return bool(words) and words[-1] in LOCATION_CUES


def ancestor_ids(conn: psycopg.Connection[Any], place_ids: list[int]) -> dict[int, set[int]]:
    """Ancestors (parents, grandparents, …) of each place, from the stored hierarchy."""
    if not place_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """WITH RECURSIVE chain AS (
                   SELECT id AS origin, parent_place_id AS ancestor, 1 AS depth FROM places WHERE id = ANY(%s)
                   UNION ALL
                   SELECT c.origin, p.parent_place_id, c.depth + 1 FROM chain c JOIN places p ON p.id = c.ancestor
                    WHERE c.ancestor IS NOT NULL AND c.depth < 6)
               SELECT origin, ancestor FROM chain WHERE ancestor IS NOT NULL""",
            (place_ids,),
        )
        result: dict[int, set[int]] = {pid: set() for pid in place_ids}
        for origin, ancestor in cur.fetchall():
            result[origin].add(ancestor)
    return result


def gather_evidence(
    mentions: list[MentionResult], text: str, title_chars: int, lead_chars: int
) -> dict[int, PlaceEvidence]:
    evidence: dict[int, PlaceEvidence] = {}
    for mention in mentions:
        if mention.decision is None:
            continue
        item = evidence.setdefault(mention.decision.place_id, PlaceEvidence(mention.decision))
        item.mentions += 1
        item.first_start = min(item.first_start, mention.start)
        item.in_headline |= mention.start < title_chars
        item.in_lead |= title_chars <= mention.start < title_chars + lead_chars
        item.cue |= has_cue(text, mention.start)
    return evidence


def select_event_location(
    conn: psycopg.Connection[Any],
    mentions: list[MentionResult],
    text: str,
    *,
    title_chars: int = 0,
    lead_chars: int = 400,
    outlet_country: str | None = None,
) -> EventLocation | None:
    evidence = gather_evidence(mentions, text, title_chars, lead_chars)
    if not evidence:
        return None
    ancestors = ancestor_ids(conn, list(evidence))
    for pid, item in evidence.items():
        related = {o for o in evidence if o != pid and (o in ancestors[pid] or pid in ancestors.get(o, set()))}
        same_country = [o for o, e in evidence.items() if o != pid and e.place.country_code == item.place.country_code]
        item.consistent_with = len(related) + len(same_country)
        level = item.place.location_level or "city"
        item.features = {
            "headline": float(item.in_headline),
            "lead": float(item.in_lead),
            "cue": float(item.cue),
            "specificity": SPECIFICITY.get(level, 3) - 3.0,
            "count": math.log1p(item.mentions),
            "consistent": min(item.consistent_with, 3) / 3.0,
            "first": 1.0 if item.first_start < max(title_chars, 200) else 0.0,
        }
        item.score = sum(WEIGHTS[name] * value for name, value in item.features.items())
    best = max(evidence.values(), key=lambda e: (e.score, SPECIFICITY.get(e.place.location_level or "city", 3)))
    # Prefer the most specific place that is consistent with the winner (inside it) when nearly as well supported.
    inside = [
        e
        for e in evidence.values()
        if e.place.place_id != best.place.place_id
        and best.place.place_id in ancestors[e.place.place_id]
        and e.score >= best.score - 1.0
    ]
    if inside:
        best = max(inside, key=lambda e: (SPECIFICITY.get(e.place.location_level or "city", 3), e.score))

    place = best.place
    uncertainty = float(place.uncertainty_km or 25.0)
    level = place.location_level or "city"
    widened = False
    peers = [
        e
        for e in evidence.values()
        if e is not best
        and e.score >= 0.6 * best.score
        and (e.in_headline or e.in_lead)
        and e.place.place_id not in ancestors[best.place.place_id]
        and best.place.place_id not in ancestors[e.place.place_id]
    ]
    if peers:
        spread = max(
            haversine_km(place.lat, place.lon, p.place.lat, p.place.lon) + float(p.place.uncertainty_km or 0)
            for p in peers
        )
        if spread > uncertainty:
            uncertainty, widened = spread, True
    total = sum(math.exp(e.score) for e in evidence.values())
    share = math.exp(best.score) / total
    penalty = 0.85 if outlet_country and place.country_code == outlet_country and level == "country" else 1.0
    confidence = round(min(0.99, share * penalty * (0.6 + 0.4 * (best.in_headline or best.in_lead))), 3)
    return EventLocation(
        place,
        place.lat,
        place.lon,
        round(uncertainty, 1),
        level,
        bool(place.country_level or level == "country"),
        confidence,
        sorted(evidence.values(), key=lambda e: -e.score),
        widened,
    )
