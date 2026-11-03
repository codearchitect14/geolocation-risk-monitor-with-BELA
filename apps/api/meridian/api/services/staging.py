"""Staged asset uploads: column mapping, place resolution for city plus country rows, and the review step.

A staged upload parses and checks every row without creating assets. Each row gets one status:
  ready      coordinates are valid, or a single confident place match was found
  review     the place is ambiguous or the match is weak; candidates are listed for a person to pick
  duplicate  repeats an earlier row of the same file (same external_id, or same name and position)
  error      the row cannot be used; the message says why
Commit creates assets only from ready rows and from review rows with a chosen candidate. Address level geocoding is out of
scope: a city row is placed at the place centroid and marked location_source = place with the place uncertainty.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from meridian.api.errors import ProblemError
from meridian.api.services import uploads as up
from meridian.api.services.uploads import GEOMETRY_TYPES, clean_text

FIELDS = ("name", "lat", "lon", "city", "country", "criticality", "type", "external_id", "tags")
SYNONYMS: dict[str, tuple[str, ...]] = {
    "name": ("name", "asset", "asset_name", "site", "site_name", "facility", "facility_name"),
    "lat": ("lat", "latitude", "y"),
    "lon": ("lon", "lng", "long", "longitude", "x"),
    "city": ("city", "town", "municipality", "locality", "location"),
    "country": ("country", "country_code", "iso2", "nation"),
    "criticality": ("criticality", "priority", "importance"),
    "type": ("type", "asset_type"),
    "external_id": ("external_id", "id", "asset_id", "code", "reference"),
    "tags": ("tags", "labels"),
}
CONFIDENT = 0.62  # place score at or above which a single match is accepted without review
MARGIN = 0.12  # lead over the runner up that makes a match unambiguous
CANDIDATES = 5
SETTLEMENT_TYPES = {"city", "town", "village", "admin1", "admin2", "admin_region", "seaport", "airport"}

TEMPLATE_CSV = (
    "name,lat,lon,city,country,criticality,type,external_id,tags\n"
    "Example terminal (illustrative),51.95,4.14,,,4,site,EX-001,port|terminal\n"
    "Example depot (illustrative),,,Rotterdam,NL,3,site,EX-002,depot\n"
)
TEMPLATE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [4.14, 51.95]},
            "properties": {"name": "Example terminal (illustrative)", "criticality": 4, "external_id": "EX-001"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[4.1, 51.9], [4.5, 52.0]]},
            "properties": {"name": "Example route (illustrative)", "criticality": 3, "external_id": "EX-002"},
        },
    ],
}


@dataclass
class Staged:
    kind: str
    rows_total: int
    mapping: dict[str, str]
    headers: list[str]
    rows: list[dict[str, Any]]


def detect_mapping(headers: list[str]) -> dict[str, str]:
    lowered = {h.strip().lower(): h for h in headers}
    found: dict[str, str] = {}
    for field, names in SYNONYMS.items():
        for candidate in names:
            if candidate in lowered and lowered[candidate] not in found.values():
                found[field] = lowered[candidate]
                break
    return found


def validate_mapping(mapping: dict[str, Any], headers: list[str]) -> dict[str, str]:
    clean: dict[str, str] = {}
    for field, column in mapping.items():
        if field not in FIELDS:
            raise ProblemError(422, f"Unknown field {field!r} in the column mapping.", code="invalid-mapping")
        if not isinstance(column, str) or column not in headers:
            raise ProblemError(422, f"Column {str(column)[:40]!r} is not in the file.", code="invalid-mapping")
        clean[field] = column
    return clean


def _row_base(number: int) -> dict[str, Any]:
    return {"row": number, "status": "ready", "message": None, "candidates": []}


def _place_view(h: Any) -> dict[str, Any]:
    return {
        "place_id": h.place_id,
        "name": h.name,
        "type": h.type,
        "country_code": h.country_code,
        "admin1": h.admin1_name,
        "population": h.population,
        "lat": h.lat,
        "lon": h.lon,
        "uncertainty_km": h.uncertainty_km,
        "score": round(h.score, 3),
    }


class PlaceResolver:
    """City plus country to place candidates, with a per-upload cache."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self._cache: dict[tuple[str, str | None], list[Any]] = {}
        self._countries: dict[str, str | None] = {}

    def country_code(self, text: str) -> str | None:
        key = text.strip()
        if not key:
            return None
        if len(key) == 2 and key.isalpha():
            return key.upper()
        if key not in self._countries:
            from meridian.geo.search import search_places

            hits = [h for h in search_places(self.conn, key, k=3) if h.type == "country"]
            self._countries[key] = hits[0].country_code if hits else None
        return self._countries[key]

    def candidates(self, city: str, country_code: str | None) -> list[Any]:
        key = (city.lower(), country_code)
        if key not in self._cache:
            from meridian.geo.search import search_places

            hits = search_places(self.conn, city, k=12, country_code=country_code)
            hits = [h for h in hits if h.type in SETTLEMENT_TYPES and (country_code is None or h.country_code == country_code)]
            self._cache[key] = hits[:CANDIDATES]
        return self._cache[key]


def _apply_place(row: dict[str, Any], hit: Any) -> None:
    row["geometry"] = {"type": "Point", "coordinates": [hit.lon, hit.lat]}
    row["country_code"] = row.get("country_code") or hit.country_code
    row["place"] = {"place_id": hit.place_id, "name": hit.name, "uncertainty_km": hit.uncertainty_km}


def resolve_row(row: dict[str, Any], city: str, country_text: str, resolver: PlaceResolver) -> None:
    code = resolver.country_code(country_text) if country_text else None
    if country_text and code is None:
        row.update(status="error", message=f"country {country_text[:40]!r} was not recognised")
        return
    hits = resolver.candidates(city, code)
    if not hits:
        row.update(status="error", message=f"no place named {city[:60]!r} was found" + (f" in {code}" if code else ""))
        return
    row["candidates"] = [_place_view(h) for h in hits]
    top = hits[0]
    margin = top.score - hits[1].score if len(hits) > 1 else 1.0
    if code and top.score >= CONFIDENT and margin >= MARGIN:
        _apply_place(row, top)
        row["confidence"] = round(top.score, 3)
        return
    row["status"] = "review"
    row["confidence"] = round(top.score, 3)
    row["message"] = (
        "several places match; pick one" if len(hits) > 1 and margin < MARGIN else "low confidence match; confirm the place"
    )
    if not code:
        row["message"] = "no country given; confirm the place"
    _apply_place(row, top)  # provisional position for the map preview; the reviewer confirms or changes it


def _coordinates(row: dict[str, Any], raw: dict[str, Any], mapping: dict[str, str]) -> bool:
    """Fill the point from lat and lon cells. Returns False when the row has no coordinate cells at all."""
    lat_raw, lon_raw = raw.get(mapping.get("lat", ""), ""), raw.get(mapping.get("lon", ""), "")
    if str(lat_raw).strip() == "" and str(lon_raw).strip() == "":
        return False
    try:
        lat, lon = float(lat_raw), float(lon_raw)
    except (TypeError, ValueError):
        row.update(status="error", message="lat and lon must be numbers")
        return True
    if not up.valid_position(lon, lat):
        row.update(status="error", message="coordinates are outside the valid range")
    else:
        row["geometry"] = {"type": "Point", "coordinates": [lon, lat]}
    return True


def stage_csv(text: str, mapping_in: dict[str, Any] | None, conn: Any, max_rows: int) -> Staged:
    reader = csv.reader(io.StringIO(text))
    try:
        headers = [h.strip() for h in next(reader)]
    except StopIteration as exc:
        raise ProblemError(422, "The file is empty.", code="invalid-upload") from exc
    mapping = validate_mapping(mapping_in, headers) if mapping_in else detect_mapping(headers)
    has_point = "lat" in mapping and "lon" in mapping
    has_place = "city" in mapping
    if "name" not in mapping or not (has_point or has_place):
        raise ProblemError(
            422,
            "Map a name column and either lat and lon columns or a city column.",
            code="mapping-required",
            extra={"headers": headers, "detected": mapping},
        )
    resolver = PlaceResolver(conn)
    rows: list[dict[str, Any]] = []
    total = 0
    for number, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        total += 1
        if total > max_rows:
            raise ProblemError(413, f"The file has more than {max_rows} rows.", code="too-many-rows")
        raw = dict(zip(headers, cells, strict=False))
        row = _row_base(number)
        row["name"] = clean_text(raw.get(mapping["name"], ""))
        row["external_id"] = clean_text(raw.get(mapping.get("external_id", ""), ""), 100) or None
        row["country_code"] = up._country(raw.get(mapping.get("country", ""))) if len(str(raw.get(mapping.get("country", ""), "")).strip()) == 2 else None
        row["tags"] = [clean_text(t, 40) for t in (raw.get(mapping.get("tags", ""), "") or "").split("|") if t.strip()][:10]
        crit = up._criticality(raw.get(mapping.get("criticality", "")))
        row["criticality"] = crit if crit is not None else 3
        row["type"] = "site"
        if not row["name"]:
            row.update(status="error", message="name is required")
        elif crit is None:
            row.update(status="error", message="criticality must be 1 to 5")
        else:
            used_coordinates = has_point and _coordinates(row, raw, mapping)
            if row["status"] == "ready" and not used_coordinates:
                city = clean_text(raw.get(mapping.get("city", ""), ""), 120)
                if not city:
                    row.update(status="error", message="needs coordinates or a city")
                else:
                    resolve_row(row, city, clean_text(raw.get(mapping.get("country", ""), ""), 80), resolver)
        rows.append(row)
    return Staged("csv", total, mapping, headers, flag_duplicates(rows))


def stage_geojson(text: str, max_rows: int, max_vertices: int) -> Staged:
    parsed = up.parse_geojson(text, max_rows, max_vertices)
    rows = [
        {
            **_row_base(i + 1),
            "name": a.name,
            "type": a.type,
            "geometry": a.geometry,
            "criticality": a.criticality,
            "country_code": a.country_code,
            "external_id": a.external_id,
            "tags": a.tags,
        }
        for i, a in enumerate(parsed.assets)
    ]
    rows += [{**_row_base(e["row"]), "status": "error", "message": e["message"], "name": "", "candidates": []} for e in parsed.errors]
    rows.sort(key=lambda r: r["row"])
    return Staged("geojson", parsed.rows_total, {}, [], flag_duplicates(rows))


def flag_duplicates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    seen_positions: set[tuple[str, str]] = set()
    for row in rows:
        if row["status"] == "error":
            continue
        if row.get("external_id"):
            if row["external_id"] in seen_ids:
                row.update(status="duplicate", message="external_id repeats an earlier row")
                continue
            seen_ids.add(row["external_id"])
        geometry = row.get("geometry")
        if geometry and row["status"] == "ready":
            key = (row["name"].lower(), json.dumps(geometry["coordinates"])[:80])
            if key in seen_positions:
                row.update(status="duplicate", message="same name and position as an earlier row")
                continue
            seen_positions.add(key)
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(("ready", "review", "duplicate", "error"), 0)
    for r in rows:
        counts[r["status"]] += 1
    return counts


def preview_features(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """GeoJSON for the map preview: every row that has a position, with its status."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": r["row"],
                "geometry": r["geometry"],
                "properties": {k: r.get(k) for k in ("row", "name", "status", "confidence", "message")},
            }
            for r in rows
            if r.get("geometry")
        ][:5000],
    }


def geometry_type_for(geometry: dict[str, Any]) -> str:
    return GEOMETRY_TYPES[geometry["type"]]


def choose(row: dict[str, Any], place_id: int) -> bool:
    """Apply a reviewer's pick. The pick must be one of the stored candidates."""
    for c in row.get("candidates", []):
        if c["place_id"] == place_id:
            row["geometry"] = {"type": "Point", "coordinates": [c["lon"], c["lat"]]}
            row["country_code"] = row.get("country_code") or c["country_code"]
            row["place"] = {"place_id": c["place_id"], "name": c["name"], "uncertainty_km": c["uncertainty_km"]}
            row["status"] = "ready"
            row["message"] = "confirmed by a reviewer"
            return True
    return False
