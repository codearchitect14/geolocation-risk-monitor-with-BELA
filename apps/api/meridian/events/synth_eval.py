"""Exposure alert evaluation on synthetic scenarios with known true nearby assets.

Each scenario places one event and a set of assets. Ground truth is whether an asset lies inside the event's true impact
radius. The radii below are written down here, independent of the lambda and weight parameters in events_config, so the
evaluation does not grade the scoring function against itself. The reported event location is the true location moved by
noise, and some events are placed only at region level, to measure how location error affects alerts.

Scenarios are synthetic. Results describe the scoring logic under the assumptions stated in the output, not real-world
performance. Everything runs in a transaction that is rolled back.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import sys
from typing import Any

from meridian.db import connect
from meridian.events import exposure
from meridian.events.config import LEVELS, load_events_config

NOW = dt.datetime(2026, 11, 2, 15, 0, tzinfo=dt.UTC)
# (type, subtype, severity, true impact radius km, reported uncertainty km for a city level report)
KINDS = [
    ("industrial_accident", "fire", 3, 5.0),
    ("industrial_accident", "explosion", 4, 10.0),
    ("natural_hazard", "flood", 3, 40.0),
    ("natural_hazard", "storm", 3, 60.0),
    ("natural_hazard", "wildfire", 3, 25.0),
    ("transport_disruption", "port_closure", 3, 15.0),
]


def offset(lat: float, lon: float, distance_km: float, bearing: float) -> tuple[float, float]:
    d = distance_km / 6371.0
    la1, lo1 = math.radians(lat), math.radians(lon)
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(bearing))
    lo2 = lo1 + math.atan2(math.sin(bearing) * math.sin(d) * math.cos(la1), math.cos(d) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


def run(scenarios: int, assets_per: int, seed: int) -> dict[str, Any]:
    cfg = load_events_config()
    rng = random.Random(seed)  # noqa: S311 - synthetic scenarios
    tp = dict.fromkeys(LEVELS, 0)
    fp = dict.fromkeys(LEVELS, 0)
    fn = dict.fromkeys(LEVELS, 0)
    breakdown: dict[str, dict[str, int]] = {}
    with connect() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO tenants (name, slug, is_demo) VALUES ('synthetic eval', 'synthetic-eval', true) RETURNING id"
                )
                tenant = cur.fetchone()[0]  # type: ignore[index]
            for _ in range(scenarios):
                kind, subtype, severity, true_radius = rng.choice(KINDS)
                true_lat, true_lon = rng.uniform(-50, 60), rng.uniform(-120, 140)
                regional = rng.random() < 0.2  # reported only at region level, centroid far from the true site
                noise_km = rng.uniform(60, 150) if regional else abs(rng.gauss(0, 8))
                rep_lat, rep_lon = offset(true_lat, true_lon, noise_km, rng.uniform(0, 2 * math.pi))
                level, uncertainty = ("admin1", 100.0) if regional else ("city", 25.0)
                confirmed = rng.random() < 0.5
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM assets WHERE tenant_id = %s", (tenant,))
                    truth: dict[str, bool] = {}
                    for i in range(assets_per):
                        # About a third of assets are near the true location (within 3x the radius), the rest far away.
                        near = rng.random() < 0.35
                        distance = rng.uniform(0, 3 * true_radius) if near else rng.uniform(100, 400)
                        a_lat, a_lon = offset(true_lat, true_lon, distance, rng.uniform(0, 2 * math.pi))
                        cur.execute(
                            """INSERT INTO assets (tenant_id, name, type, geom, criticality)
                               VALUES (%s, %s, 'site', ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s) RETURNING id""",
                            (tenant, f"a{i}", a_lon, a_lat, rng.choice([2, 3, 4, 5])),
                        )
                        truth[str(cur.fetchone()[0])] = distance <= true_radius  # type: ignore[index]
                    cur.execute(
                        """INSERT INTO events (type, subtype, severity, status, first_seen_at, last_seen_at, occurred_at, title, geom,
                                               uncertainty_km, location_level, location_confidence, reliability, confirmation)
                           VALUES (%s, %s, %s, 'new', %s, %s, %s, 'synthetic', ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s, %s)
                           RETURNING id""",
                        (
                            kind,
                            subtype,
                            severity,
                            NOW,
                            NOW,
                            NOW,
                            rep_lon,
                            rep_lat,
                            uncertainty,
                            level,
                            0.6 if regional else 0.85,
                            0.9 if confirmed else 0.6,
                            "confirmed" if confirmed else "unconfirmed",
                        ),
                    )
                    event_id = str(cur.fetchone()[0])  # type: ignore[index]
                exposure.compute_for_event(conn, cfg, event_id, NOW)
                with conn.cursor() as cur:
                    cur.execute("SELECT asset_id, level FROM exposures WHERE event_id = %s", (event_id,))
                    scored = {str(a): lvl for a, lvl in cur.fetchall()}
                group = "regional" if regional else "city"
                for asset_id, is_true in truth.items():
                    rank = LEVELS.index(scored[asset_id]) if asset_id in scored else -1
                    for floor, name in enumerate(LEVELS):
                        flagged = rank >= floor
                        bucket = breakdown.setdefault(f"{group}:{name}", {"tp": 0, "fp": 0, "fn": 0})
                        if flagged and is_true:
                            tp[name] += 1
                            bucket["tp"] += 1
                        elif flagged and not is_true:
                            fp[name] += 1
                            bucket["fp"] += 1
                        elif is_true:
                            fn[name] += 1
                            bucket["fn"] += 1
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM events WHERE id = %s", (event_id,))
        finally:
            conn.rollback()

    def rates(t: int, f: int, n: int) -> dict[str, float | None]:
        return {
            "precision": round(t / (t + f), 3) if t + f else None,
            "recall": round(t / (t + n), 3) if t + n else None,
        }

    return {
        "note": "synthetic scenarios; ground truth radii are independent of scoring parameters",
        "seed": seed,
        "scenarios": scenarios,
        "assets_per_scenario": assets_per,
        "true_impact_radius_km": {f"{k[0]}/{k[1]}": k[3] for k in KINDS},
        "assumptions": "20% of reports are region level with 60 to 150 km location error; other reports have about 8 km error",
        "alert_if_level_at_least": {name: rates(tp[name], fp[name], fn[name]) for name in LEVELS},
        "by_report_kind": {key: rates(v["tp"], v["fp"], v["fn"]) for key, v in sorted(breakdown.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenarios", type=int, default=400)
    parser.add_argument("--assets", type=int, default=30)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()
    print(json.dumps(run(args.scenarios, args.assets, args.seed), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
