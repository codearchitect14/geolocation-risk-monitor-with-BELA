"""Feed file ingestion: minimum magnitudes, assets nearby, replay scoring, and idempotent re-runs."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import psycopg

from meridian.events import cli, service
from meridian.events.config import load_events_config
from tests.events_support import NOW, reset_events, seed_tenant

CFG = load_events_config()


def quake(ref: str, mag: float, lat: float, lon: float, when: dt.datetime = NOW) -> dict[str, Any]:
    ms = int(when.timestamp() * 1000)
    return {
        "feature": {
            "id": ref,
            "properties": {
                "mag": mag,
                "time": ms,
                "updated": ms,
                "type": "earthquake",
                "title": f"M {mag}",
                "place": "test",
            },
            "geometry": {"type": "Point", "coordinates": [lon, lat, 10.0]},
        }
    }


def write(tmp_path: Path, rows: list[dict[str, Any]]) -> list[Path]:
    path = tmp_path / "usgs.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return [path]


def test_small_quakes_are_kept_only_near_assets(conn: psycopg.Connection[Any], tmp_path: Path) -> None:
    reset_events(conn)
    seed_tenant(conn, [("site", 39.80, -89.64, 5)])
    rows = [
        quake("far-small", 3.0, 10.0, 10.0),
        quake("near-small", 3.0, 39.9, -89.7),
        quake("tiny", 1.5, 39.8, -89.6),
        quake("big-far", 5.2, -20.0, -70.0),
    ]
    run = service.ingest_usgs(conn, CFG, write(tmp_path, rows), now=NOW)
    assert run.skipped == {"small_and_far_from_assets": 1, "below_minimum_magnitude": 1}
    assert run.actions["created"] == 2


def test_rerunning_the_same_file_changes_nothing(conn: psycopg.Connection[Any], tmp_path: Path) -> None:
    reset_events(conn)
    seed_tenant(conn, [("site", 39.80, -89.64, 5)])
    files = write(tmp_path, [quake("q1", 6.5, 39.85, -89.6)])
    first = service.ingest_usgs(conn, CFG, files, now=NOW)
    second = service.ingest_usgs(conn, CFG, files, now=NOW)
    assert first.actions["created"] == 1 and first.alerts.created == 1
    assert second.actions == {"duplicate": 1} and second.alerts.created == 0
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM events")
        assert cur.fetchone() == (1,)


def test_replay_scores_as_of_the_record_time(conn: psycopg.Connection[Any], tmp_path: Path) -> None:
    reset_events(conn)
    seed_tenant(conn, [("site", 39.80, -89.64, 5)])
    old = NOW - dt.timedelta(days=20)
    files = write(tmp_path, [quake("old", 6.5, 39.85, -89.6, old)])
    live = service.ingest_usgs(conn, CFG, files, now=NOW)  # 20 days later the recency decay removes the exposure
    assert live.alerts.created == 0
    reset_events(conn)
    seed_tenant(conn, [("site", 39.80, -89.64, 5)])
    replay = service.ingest_usgs(conn, CFG, files, replay=True)
    assert replay.alerts.created == 1


def test_demo_tenant_is_labeled_and_repeatable(conn: psycopg.Connection[Any]) -> None:
    reset_events(conn)
    from tests.events_support import seed_places

    seed_places(conn)
    first = cli.demo_tenant(conn, 3, 7)
    second = cli.demo_tenant(conn, 3, 7)
    assert first["assets"] == second["assets"] == 3
    with conn.cursor() as cur:
        cur.execute("SELECT name, is_demo FROM tenants WHERE slug = %s", (cli.DEMO_SLUG,))
        assert cur.fetchall() == [("Illustrative demo tenant (synthetic data)", True)]
        cur.execute("SELECT count(*) FROM assets WHERE 'synthetic' = ANY(tags)")
        assert cur.fetchone() == (3,)
