"""Article level context used by the re-ranker: countries named in the text, the outlet country,
already resolved places, and qualifier detection ("Springfield, Illinois")."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import psycopg

from meridian.geo.names import normalize_name
from meridian.linking.spans import capitalized_spans
from meridian.linking.types import PlaceRecord

_QUALIFIER = re.compile(
    r"^\s*(?:,|\()\s*([^\W\d_][\w'.\- ]{1,40}?)\s*(?=[,.;:)]|\s+(?:and|said|on|in|at|a|an|the)\b|$)", re.UNICODE
)


class CountryIndex:
    """Country names and aliases to ISO codes, loaded once from the place table."""

    def __init__(self, names: dict[str, str], by_code: dict[str, str]) -> None:
        self.names = names
        self.by_code = by_code

    @classmethod
    def load(cls, conn: psycopg.Connection[Any]) -> CountryIndex:
        names: dict[str, str] = {}
        by_code: dict[str, str] = {}
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name_normalized, country_code FROM places WHERE type = 'country' AND country_code IS NOT NULL"
            )
            rows = cur.fetchall()
            ids = {r[0]: r[2] for r in rows}
            for _, normalized, code in rows:
                names[normalized] = code
                by_code[code] = normalized
            cur.execute("SELECT place_id, alias_normalized FROM place_aliases WHERE place_id = ANY(%s)", (list(ids),))
            for place_id, alias in cur.fetchall():
                names.setdefault(alias, ids[place_id])
            cur.execute("SELECT iso2, name FROM ref_country_info")
            for iso2, name in cur.fetchall():
                names.setdefault(normalize_name(name), iso2)
                by_code.setdefault(iso2, normalize_name(name))
        return cls(names, by_code)

    def countries_in_text(self, text: str) -> set[str]:
        found: set[str] = set()
        for span in capitalized_spans(text, max_words=4):
            code = self.names.get(normalize_name(span.text))
            if code:
                found.add(code)
        return found


@dataclass
class ArticleContext:
    text: str
    lang: str | None = None
    outlet_country: str | None = None
    named_countries: set[str] = field(default_factory=set)
    resolved: list[PlaceRecord] = field(default_factory=list)  # places of accepted mentions

    def centroid(self, exclude_place_id: int | None = None) -> tuple[float, float] | None:
        points = [(p.lat, p.lon) for p in self.resolved if p.place_id != exclude_place_id]
        if not points:
            return None
        lats = sorted(p[0] for p in points)
        lons = sorted(p[1] for p in points)
        return lats[len(lats) // 2], lons[len(lons) // 2]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def qualifier_after(text: str, end: int) -> str | None:
    """The word group right after a mention when it is introduced by a comma or parenthesis."""
    match = _QUALIFIER.match(text[end : end + 60])
    return normalize_name(match.group(1)) if match else None
