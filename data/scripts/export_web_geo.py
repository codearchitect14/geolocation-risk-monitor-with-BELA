"""Export country outlines and recent incident points for the marketing site.

Outputs (committed, regenerated on demand):
  apps/web/public/geo/countries.geojson      simplified Natural Earth country polygons for the MapLibre component
  apps/web/src/content/world.json            one SVG path per country in an equirectangular projection, plus the
                                             most recent located incidents from the demonstration database
Only public reference geometry and public hazard records are exported. No tenant data is read.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import psycopg

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web"
URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://meridian:meridian@localhost:5433/meridian").replace(
    "postgresql+psycopg://", "postgresql://", 1
)
LAT_MIN, LAT_MAX = -58.0, 80.0
WIDTH = 1000
HEIGHT = round(WIDTH * (LAT_MAX - LAT_MIN) / 360)


def project(lon: float, lat: float) -> tuple[float, float]:
    return (lon + 180.0) / 360.0 * WIDTH, (LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * HEIGHT


def ring_path(ring: list[list[float]]) -> str:
    pts = [project(x, y) for x, y in ring]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    if (max(xs) - min(xs)) * (max(ys) - min(ys)) < 6:  # islands smaller than a few pixels add bytes and no information
        return ""
    return "M" + "L".join(f"{x:.0f} {y:.0f}" for x, y in pts) + "Z"


def geometry_path(geometry: dict[str, Any]) -> str:
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return "".join(ring_path(ring) for polygon in polygons for ring in polygon[:1])


def main() -> None:
    with psycopg.connect(URL) as conn:
        small = conn.execute(
            """SELECT country_code, name, ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.15), 2)::json
                 FROM places WHERE type = 'country' AND has_polygon AND geom IS NOT NULL ORDER BY name"""
        ).fetchall()
        coarse = conn.execute(
            """SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.7), 1)::json
                 FROM places
                WHERE type = 'country' AND has_polygon AND geom IS NOT NULL AND country_code <> 'AQ' ORDER BY name"""
        ).fetchall()
        incidents = conn.execute(
            """SELECT e.type, e.severity, ST_Y(ST_Centroid(e.geom)), ST_X(ST_Centroid(e.geom))
                 FROM events e JOIN event_sources s ON s.event_id = e.id
                WHERE e.geom IS NOT NULL AND s.source_kind = 'usgs'
                  AND ST_Y(ST_Centroid(e.geom)) BETWEEN %s AND %s
                ORDER BY e.last_seen_at DESC LIMIT 18""",
            (LAT_MIN, LAT_MAX),
        ).fetchall()
    features = [
        {"type": "Feature", "properties": {"iso2": iso2, "name": name}, "geometry": geom} for iso2, name, geom in small
    ]
    out = WEB / "public" / "geo"
    out.mkdir(parents=True, exist_ok=True)
    (out / "countries.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")), encoding="utf-8"
    )
    paths = [geometry_path(g) for (g,) in coarse if g]
    points = []
    for kind, severity, lat, lon in incidents:
        x, y = project(lon, lat)
        points.append(
            {
                "x": round(x, 1),
                "y": round(y, 1),
                "lon": round(lon, 2),
                "lat": round(lat, 2),
                "level": int(severity),
                "type": kind,
            }
        )
    world: dict[str, Any] = {"width": WIDTH, "height": HEIGHT, "d": "".join(paths), "incidents": points}
    (WEB / "src" / "content" / "world.json").write_text(json.dumps(world, separators=(",", ":")), encoding="utf-8")
    print(f"countries={len(features)} svg_bytes={len(''.join(paths))} incidents={len(points)}")


if __name__ == "__main__":
    main()
