"""Asset file parsing with strict limits: size and rows, coordinate ranges, geometry complexity, and valid geometry."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import shape

from meridian.api.errors import ProblemError

MAX_NAME = 200
GEOMETRY_TYPES = {
    "Point": "site",
    "LineString": "route",
    "MultiLineString": "route",
    "Polygon": "region",
    "MultiPolygon": "region",
}
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass
class AssetInput:
    name: str
    type: str
    geometry: dict[str, Any]
    criticality: int = 3
    country_code: str | None = None
    external_id: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class Parsed:
    kind: str
    rows_total: int
    assets: list[AssetInput]
    errors: list[dict[str, Any]]


def clean_text(value: str, limit: int = MAX_NAME) -> str:
    return _CONTROL.sub("", value).strip()[:limit]


def csv_safe(cell: Any) -> Any:
    """Prefix cells that a spreadsheet would treat as a formula."""
    if isinstance(cell, str) and cell[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + cell
    return cell


def decode(data: bytes) -> str:
    if b"\x00" in data[:4096]:
        raise ProblemError(415, "The file is not a text file.", code="unsupported-file")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProblemError(415, "The file must be UTF-8 text.", code="unsupported-file") from exc


def sniff_kind(filename: str, content_type: str, text: str) -> str:
    stripped = text.lstrip()
    looks_json = stripped.startswith("{")
    if filename.lower().endswith((".geojson", ".json")) or "json" in content_type:
        if not looks_json:
            raise ProblemError(415, "The file does not contain GeoJSON.", code="unsupported-file")
        return "geojson"
    if (
        filename.lower().endswith(".csv")
        or "csv" in content_type
        or content_type in {"text/plain", "application/vnd.ms-excel"}
    ):
        if looks_json:
            raise ProblemError(415, "The file content does not match its type.", code="unsupported-file")
        return "csv"
    raise ProblemError(415, "Upload a .csv or .geojson file.", code="unsupported-file")


def count_vertices(coords: Any) -> int:
    if isinstance(coords, list) and coords and isinstance(coords[0], int | float):
        return 1
    return sum(count_vertices(c) for c in coords) if isinstance(coords, list) else 0


def valid_position(lon: Any, lat: Any) -> bool:
    return (
        isinstance(lon, int | float)
        and isinstance(lat, int | float)
        and not isinstance(lon, bool)
        and not isinstance(lat, bool)
        and -180 <= lon <= 180
        and -90 <= lat <= 90
    )


def _check_geometry(geometry: dict[str, Any], max_vertices: int) -> str | None:
    kind = geometry.get("type")
    if kind not in GEOMETRY_TYPES:
        return f"geometry type {kind!r} is not supported"
    coords = geometry.get("coordinates")
    if count_vertices(coords) > max_vertices:
        return "geometry has too many vertices"
    if kind == "Point":
        if not (isinstance(coords, list) and len(coords) >= 2 and valid_position(coords[0], coords[1])):
            return "coordinates are outside the valid range"
        return None
    try:
        geo = shape(geometry)
    except (ValueError, TypeError, AttributeError, IndexError):
        return "geometry is malformed"
    xmin, ymin, xmax, ymax = geo.bounds
    if not (valid_position(xmin, ymin) and valid_position(xmax, ymax)):
        return "coordinates are outside the valid range"
    if not geo.is_valid or geo.is_empty:
        return "geometry is not valid"
    return None


def _criticality(raw: Any) -> int | None:
    if raw in (None, ""):
        return 3
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return None
    return value if 1 <= value <= 5 else None


def _country(raw: Any) -> str | None:
    value = str(raw or "").strip().upper()
    return value if re.fullmatch(r"[A-Z]{2}", value) else None


def parse_csv(text: str, max_rows: int, max_vertices: int) -> Parsed:
    reader = csv.DictReader(io.StringIO(text))
    fields = [f.strip().lower() for f in (reader.fieldnames or [])]
    reader.fieldnames = fields
    lat_key = "lat" if "lat" in fields else "latitude"
    lon_key = "lon" if "lon" in fields else "lng" if "lng" in fields else "longitude"
    if "name" not in fields or lat_key not in fields or lon_key not in fields:
        raise ProblemError(422, "The CSV needs the columns name, lat, and lon.", code="invalid-upload")
    assets: list[AssetInput] = []
    errors: list[dict[str, Any]] = []
    total = 0
    for number, row in enumerate(reader, start=2):
        total += 1
        if total > max_rows:
            raise ProblemError(413, f"The file has more than {max_rows} rows.", code="too-many-rows")
        name = clean_text(row.get("name") or "")
        try:
            lat, lon = float(row[lat_key]), float(row[lon_key])
        except (TypeError, ValueError):
            errors.append({"row": number, "message": "lat and lon must be numbers"})
            continue
        criticality = _criticality(row.get("criticality"))
        if not name:
            errors.append({"row": number, "message": "name is required"})
        elif not valid_position(lon, lat):
            errors.append({"row": number, "message": "coordinates are outside the valid range"})
        elif criticality is None:
            errors.append({"row": number, "message": "criticality must be 1 to 5"})
        else:
            tags = [clean_text(t, 40) for t in (row.get("tags") or "").split("|") if t.strip()][:10]
            assets.append(
                AssetInput(
                    name,
                    "site",
                    {"type": "Point", "coordinates": [lon, lat]},
                    criticality,
                    _country(row.get("country_code")),
                    clean_text(row.get("external_id") or "", 100) or None,
                    tags,
                )
            )
    return Parsed("csv", total, assets, errors)


def parse_geojson(text: str, max_rows: int, max_vertices: int) -> Parsed:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProblemError(422, "The file is not valid JSON.", code="invalid-upload") from exc
    if not isinstance(document, dict) or document.get("type") not in {"FeatureCollection", "Feature"}:
        raise ProblemError(422, "Expected a GeoJSON FeatureCollection.", code="invalid-upload")
    features = document["features"] if document["type"] == "FeatureCollection" else [document]
    if not isinstance(features, list):
        raise ProblemError(422, "Expected a list of features.", code="invalid-upload")
    if len(features) > max_rows:
        raise ProblemError(413, f"The file has more than {max_rows} features.", code="too-many-rows")
    if (
        sum(
            count_vertices((f or {}).get("geometry", {}).get("coordinates"))
            for f in features
            if isinstance(f, dict) and isinstance(f.get("geometry"), dict)
        )
        > max_vertices
    ):
        raise ProblemError(413, "The file has too many vertices.", code="too-complex")
    assets: list[AssetInput] = []
    errors: list[dict[str, Any]] = []
    for number, feature in enumerate(features, start=1):
        props = feature.get("properties") if isinstance(feature, dict) else None
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        props = props if isinstance(props, dict) else {}
        if not isinstance(geometry, dict):
            errors.append({"row": number, "message": "geometry is required"})
            continue
        problem = _check_geometry(geometry, max_vertices)
        name = clean_text(str(props.get("name") or ""))
        criticality = _criticality(props.get("criticality"))
        if problem:
            errors.append({"row": number, "message": problem})
        elif not name:
            errors.append({"row": number, "message": "properties.name is required"})
        elif criticality is None:
            errors.append({"row": number, "message": "criticality must be 1 to 5"})
        else:
            raw_tags = props.get("tags")
            tags: list[Any] = raw_tags if isinstance(raw_tags, list) else []
            assets.append(
                AssetInput(
                    name,
                    GEOMETRY_TYPES[geometry["type"]],
                    {"type": geometry["type"], "coordinates": geometry["coordinates"]},
                    criticality,
                    _country(props.get("country_code")),
                    clean_text(str(props.get("external_id") or ""), 100) or None,
                    [clean_text(str(t), 40) for t in tags[:10]],
                )
            )
    return Parsed("geojson", len(features), assets, errors)
