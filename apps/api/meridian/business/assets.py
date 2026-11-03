"""Illustrative asset portfolios for the demo tenants.

python -m meridian.business.assets [--out data/synthetic/demo_assets.csv] [--no-load]

Each synthetic tenant gets 50 to 300 fictional assets placed at real public locations from the place table (cities, seaports,
airports, and industrial sites), mostly in the tenant's own region. Names are generic and every asset carries the tag
"illustrative". The result is deterministic for a given place table and seed.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from meridian.config import get_settings
from meridian.db import connect

SEED = 42
MIN_ASSETS, MAX_ASSETS = 50, 300
SUFFIXES = {
    "city": ("Distribution Centre", "Regional Office", "Warehouse", "Service Hub", "Operations Centre"),
    "seaport": ("Port Terminal", "Container Depot", "Marine Yard", "Quayside Warehouse"),
    "airport": ("Air Cargo Hub", "Airside Depot", "Freight Terminal"),
    "industrial": ("Plant", "Processing Facility", "Works", "Production Site"),
}
TAGS = ("warehouse", "port", "manufacturing", "cold-chain", "regional", "priority", "hazmat", "retail", "data-centre", "fleet")
CRITICALITY_WEIGHTS = (1, 3, 5, 3, 1)  # criticality 1 to 5
COLUMNS = ["tenant_id", "external_id", "name", "type", "geometry", "criticality", "country_code", "tags", "place_id", "location_uncertainty_km"]


@dataclass(frozen=True)
class Spot:
    place_id: int
    name: str
    kind: str  # city, seaport, airport, industrial
    country_code: str
    region: str
    lat: float
    lon: float
    uncertainty_km: float | None


def load_spots(conn: psycopg.Connection[Any]) -> list[Spot]:
    rows = conn.execute(
        """(SELECT id, name, 'city', country_code, region_of_country(country_code), lat, lon, uncertainty_km FROM places
             WHERE type = 'city' AND population >= 150000 AND country_code IS NOT NULL ORDER BY population DESC, id LIMIT 3000)
           UNION ALL
           (SELECT id, name, 'seaport', country_code, region_of_country(country_code), lat, lon, uncertainty_km FROM places
             WHERE type = 'seaport' AND country_code IS NOT NULL ORDER BY COALESCE(sitelinks, 0) DESC, id LIMIT 1500)
           UNION ALL
           (SELECT id, name, 'airport', country_code, region_of_country(country_code), lat, lon, uncertainty_km FROM places
             WHERE type = 'airport' AND country_code IS NOT NULL ORDER BY COALESCE(sitelinks, 0) DESC, id LIMIT 1500)
           UNION ALL
           (SELECT id, name, 'industrial', country_code, region_of_country(country_code), lat, lon, uncertainty_km FROM places
             WHERE type IN ('factory', 'refinery', 'power_station') AND country_code IS NOT NULL ORDER BY COALESCE(sitelinks, 0) DESC, id LIMIT 1500)"""
    ).fetchall()
    return [Spot(r[0], r[1], r[2], r[3], r[4] or "Unknown", r[5], r[6], r[7]) for r in rows]


def circle(lat: float, lon: float, radius_km: float, points: int = 24) -> list[list[float]]:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.2))
    ring = [[round(lon + dlon * math.cos(2 * math.pi * i / points), 5), round(lat + dlat * math.sin(2 * math.pi * i / points), 5)] for i in range(points)]
    ring.append(ring[0])
    return ring


def asset_target(final_assets: int | None, plan: str | None) -> int:
    """Number of assets: the tenant's final monitored count from the usage history, kept within 50 to 300."""
    if final_assets is None:
        final_assets = {"starter": 40, "professional": 220, "enterprise": 280}.get(plan or "", 100)
    return max(MIN_ASSETS, min(MAX_ASSETS, final_assets))


def generate_rows(spots: list[Spot], tenants: list[dict[str, Any]], seed: int = SEED) -> list[dict[str, Any]]:
    rng = random.Random(seed)  # noqa: S311 - demo data, not security sensitive
    by_kind: dict[str, list[Spot]] = {}
    for s in spots:
        by_kind.setdefault(s.kind, []).append(s)
    rows: list[dict[str, Any]] = []
    for tenant in sorted(tenants, key=lambda t: str(t["id"])):
        region = tenant["region"]
        target = asset_target(tenant.get("assets"), tenant.get("plan"))
        used_names: set[str] = set()
        ports = [s for s in by_kind.get("seaport", []) if s.region == region] or by_kind.get("seaport", [])

        def pick(kind: str, home: str = region) -> Spot:
            pool = by_kind.get(kind) or spots
            local = [s for s in pool if s.region == home]
            chosen_pool = local if local and rng.random() < 0.8 else pool
            return rng.choice(chosen_pool)

        for n in range(target):
            roll = rng.random()
            geometry: dict[str, Any]
            external_id = f"DEMO-{n + 1:04d}"
            if roll < 0.10 and len(ports) >= 2:
                a, b = rng.sample(ports, 2)
                mid = [round((a.lon + b.lon) / 2 + rng.uniform(-0.3, 0.3), 5), round((a.lat + b.lat) / 2 + rng.uniform(-0.3, 0.3), 5)]
                geometry = {"type": "LineString", "coordinates": [[a.lon, a.lat], mid, [b.lon, b.lat]]}
                name, kind, spot, uncertainty = f"{a.name} to {b.name} sea route", "route", a, None
            elif roll < 0.15:
                spot = pick("city")
                geometry = {"type": "Polygon", "coordinates": [circle(spot.lat, spot.lon, rng.choice((25, 40, 60)))]}
                name, kind, uncertainty = f"{spot.name} service area", "region", None
            else:
                kind_key = rng.choices(("city", "seaport", "airport", "industrial"), weights=(45, 20, 15, 20))[0]
                spot = pick(kind_key)
                geometry = {"type": "Point", "coordinates": [spot.lon, spot.lat]}
                name, kind, uncertainty = f"{spot.name} {rng.choice(SUFFIXES[spot.kind])}", "site", spot.uncertainty_km
            if name in used_names:
                name = f"{name} {n + 1}"
            used_names.add(name)
            tags = sorted({"illustrative", *rng.sample(TAGS, rng.randint(1, 3))})
            rows.append(
                {
                    "tenant_id": tenant["id"], "external_id": external_id, "name": name, "type": kind, "geometry": geometry,
                    "criticality": rng.choices((1, 2, 3, 4, 5), weights=CRITICALITY_WEIGHTS)[0], "country_code": spot.country_code,
                    "tags": tags, "place_id": spot.place_id, "location_uncertainty_km": uncertainty,
                }
            )  # fmt: skip
    return rows


def tenant_inputs(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT t.id, t.region,
                  (SELECT assets_monitored FROM usage_daily u WHERE u.tenant_id = t.id ORDER BY date DESC LIMIT 1),
                  (SELECT plan_id FROM subscriptions s WHERE s.tenant_id = t.id ORDER BY start_date DESC LIMIT 1)
             FROM tenants t WHERE t.settings->>'synthetic' = 'true' AND t.status = 'active' ORDER BY t.id"""
    ).fetchall()
    return [{"id": str(r[0]), "region": r[1], "assets": r[2], "plan": r[3]} for r in rows]


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(COLUMNS)
        for r in rows:
            writer.writerow([json.dumps(r[c], separators=(",", ":")) if c in ("geometry", "tags") else ("" if r[c] is None else r[c]) for c in COLUMNS])


def load_rows(conn: psycopg.Connection[Any], rows: list[dict[str, Any]]) -> int:
    conn.execute("DELETE FROM assets WHERE external_id LIKE 'DEMO-%' AND tenant_id IN (SELECT id FROM tenants WHERE settings->>'synthetic' = 'true')")
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(
                """INSERT INTO assets (tenant_id, name, type, geom, criticality, country_code, tags, external_id, location_source, location_uncertainty_km, place_id)
                   VALUES (%s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s, %s, 'place', %s, %s)""",
                (r["tenant_id"], r["name"], r["type"], json.dumps(r["geometry"]), r["criticality"], r["country_code"], r["tags"], r["external_id"], r["location_uncertainty_km"], r["place_id"]),
            )
    conn.commit()
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m meridian.business.assets")
    parser.add_argument("--out", type=Path, default=get_settings().data_dir / "synthetic" / "demo_assets.csv")
    parser.add_argument("--no-load", action="store_true", help="write the file only")
    args = parser.parse_args(argv)
    conn = connect()
    try:
        spots = load_spots(conn)
        tenants = tenant_inputs(conn)
        if not spots or not tenants:
            print("Need places in the database and synthetic tenants (run make business-data first).", file=sys.stderr)
            return 1
        rows = generate_rows(spots, tenants)
        write_csv(rows, args.out)
        print(f"{len(rows)} illustrative assets for {len(tenants)} tenants written to {args.out}")
        if not args.no_load:
            print(f"{load_rows(conn, rows)} assets loaded")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
