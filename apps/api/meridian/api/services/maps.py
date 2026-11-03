"""Static map images for reports.

The map is drawn as an SVG from stored geometry only: boundary polygons from the place table, the event position with its
uncertainty circle, and the tenant's assets. No map tiles are requested, so asset positions are never sent to a third party.
A headless browser turns the SVG into a PNG (see render.py); when it is not available the SVG itself is embedded.
"""

from __future__ import annotations

import base64
import html
import math
from dataclasses import dataclass, field
from typing import Any

from meridian.api.db import Tx
from meridian.api.services import render

WIDTH, HEIGHT = 960, 540
LEVEL_COLOURS = {"critical": "#b3261e", "high": "#d9480f", "medium": "#b7791f", "low": "#2f6f4e", "none": "#5b6770"}
MAX_PATH_POINTS = 6000


@dataclass
class Marker:
    lon: float
    lat: float
    level: str = "none"
    label: str | None = None


@dataclass
class MapSpec:
    markers: list[Marker] = field(default_factory=list)
    event_point: tuple[float, float] | None = None
    circle: dict[str, Any] | None = None  # GeoJSON polygon of the uncertainty area
    title: str = ""


def _mercator(lon: float, lat: float) -> tuple[float, float]:
    lat = max(min(lat, 85.0), -85.0)
    return math.radians(lon), math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _bounds(spec: MapSpec) -> tuple[float, float, float, float]:
    points = [(m.lon, m.lat) for m in spec.markers]
    if spec.event_point:
        points.append(spec.event_point)
    if spec.circle:
        for ring in spec.circle.get("coordinates", []):
            points.extend((p[0], p[1]) for p in ring)
    if not points:
        return -180.0, -60.0, 180.0, 75.0
    lons, lats = [p[0] for p in points], [p[1] for p in points]
    west, east, south, north = min(lons), max(lons), min(lats), max(lats)
    pad_lon, pad_lat = max((east - west) * 0.15, 1.0), max((north - south) * 0.15, 0.7)
    return west - pad_lon, south - pad_lat, east + pad_lon, north + pad_lat


class Projection:
    def __init__(self, bounds: tuple[float, float, float, float]) -> None:
        west, south, east, north = bounds
        self.x0, self.y1 = _mercator(west, north)
        x1, self.y0 = _mercator(east, south)
        span_x, span_y = x1 - self.x0, self.y1 - self.y0
        self.scale = min(WIDTH / span_x, HEIGHT / span_y)
        self.offset_x = (WIDTH - span_x * self.scale) / 2
        self.offset_y = (HEIGHT - span_y * self.scale) / 2
        self.bounds = bounds

    def __call__(self, lon: float, lat: float) -> tuple[float, float]:
        x, y = _mercator(lon, lat)
        return self.offset_x + (x - self.x0) * self.scale, self.offset_y + (self.y1 - y) * self.scale

    def visible_bounds(self) -> tuple[float, float, float, float]:
        """Geographic extent actually drawn, which can exceed the requested bounds on one axis."""
        def inverse(px: float, py: float) -> tuple[float, float]:
            x = (px - self.offset_x) / self.scale + self.x0
            y = self.y1 - (py - self.offset_y) / self.scale
            return math.degrees(x), math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)

        west, north = inverse(0, 0)
        east, south = inverse(WIDTH, HEIGHT)
        return west, south, east, north


def _ring_path(ring: list[list[float]], project: Projection) -> str:
    pts = [project(p[0], p[1]) for p in ring]
    return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z"


def _polygons(geometry: dict[str, Any]) -> list[list[list[list[float]]]]:
    if geometry.get("type") == "Polygon":
        return [geometry["coordinates"]]
    if geometry.get("type") == "MultiPolygon":
        return list(geometry["coordinates"])
    return []


def boundary_geometries(tx: Tx, bounds: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    """Country outlines that touch the drawn area, simplified to the scale of the map."""
    west, south, east, north = bounds
    tolerance = max((east - west) / 400, 0.005)
    rows = tx.all(
        """SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, %s), 3)::json FROM places
            WHERE type = 'country' AND has_polygon AND geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326) LIMIT 60""",
        (tolerance, max(west, -180), max(south, -90), min(east, 180), min(north, 90)),
    )
    return [r[0] for r in rows]


def build_svg(spec: MapSpec, boundaries: list[dict[str, Any]] | None = None) -> str:
    project = Projection(_bounds(spec))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        f'aria-label="{html.escape(spec.title or "Map")}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#e8eef2"/>',
    ]
    budget = MAX_PATH_POINTS
    for geometry in boundaries or []:
        for polygon in _polygons(geometry):
            for ring in polygon:
                if budget <= 0:
                    break
                budget -= len(ring)
                parts.append(f'<path d="{_ring_path(ring, project)}" fill="#f7f5ee" stroke="#9aa5ad" stroke-width="0.8"/>')
    if spec.circle:
        for polygon in _polygons(spec.circle):
            parts.append(
                f'<path d="{_ring_path(polygon[0], project)}" fill="#d9480f" fill-opacity="0.15" stroke="#d9480f" stroke-width="1.5" stroke-dasharray="5 3"/>'
            )
    if spec.event_point:
        x, y = project(*spec.event_point)
        parts.append(
            f'<path d="M{x - 9:.1f},{y:.1f}L{x:.1f},{y - 9:.1f}L{x + 9:.1f},{y:.1f}L{x:.1f},{y + 9:.1f}Z" fill="#1f2933" stroke="#ffffff" stroke-width="1.5"/>'
        )
    for marker in spec.markers:
        x, y = project(marker.lon, marker.lat)
        colour = LEVEL_COLOURS.get(marker.level, LEVEL_COLOURS["none"])
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{colour}" stroke="#ffffff" stroke-width="1.5"/>')
        if marker.label:
            parts.append(
                f'<text x="{x + 9:.1f}" y="{y + 4:.1f}" font-family="Helvetica, Arial, sans-serif" font-size="13" '
                f'fill="#1f2933" stroke="#ffffff" stroke-width="3" paint-order="stroke">{html.escape(marker.label)}</text>'
            )
    parts.append(
        '<text x="10" y="528" font-family="Helvetica, Arial, sans-serif" font-size="11" fill="#52606d">'
        "Schematic map from stored geometry. Positions are approximate.</text></svg>"
    )
    return "".join(parts)


def map_data_uri(tx: Tx, spec: MapSpec) -> str:
    """A data URI for the report: PNG when the browser renderer works, otherwise the SVG itself."""
    project = Projection(_bounds(spec))
    try:
        boundaries = boundary_geometries(tx, project.visible_bounds())
    except Exception:  # noqa: BLE001 - a missing boundary table never blocks a report
        tx.rollback()
        boundaries = []
    svg = build_svg(spec, boundaries)
    png = render.svg_to_png(svg)
    if png:
        return "data:image/png;base64," + base64.b64encode(png).decode()
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
