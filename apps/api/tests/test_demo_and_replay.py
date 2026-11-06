"""The recorded feed replay and the demonstration seed: re-timing, pacing, idempotence, and how passwords are issued."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import psycopg
import pytest

from meridian import demo
from meridian.api.security import passwords
from meridian.events import replay
from meridian.events.config import load_events_config
from tests.events_support import make_event, reset_events, seed_places

CFG = load_events_config()
ANCHOR = dt.datetime(2026, 11, 6, 12, 0, tzinfo=dt.UTC)


def feature(ident: str, minutes_ago: float, mag: float = 5.0, lon: float = -89.6, lat: float = 39.8) -> dict[str, Any]:
    at = int((ANCHOR - dt.timedelta(days=30, minutes=minutes_ago)).timestamp() * 1000)
    return {
        "type": "Feature",
        "id": ident,
        "properties": {
            "mag": mag,
            "place": "test place",
            "time": at,
            "updated": at,
            "type": "earthquake",
            "title": f"M {mag} - test place",
            "status": "reviewed",
            "tsunami": 0,
        },
        "geometry": {"type": "Point", "coordinates": [lon, lat, 10.0]},
    }


@pytest.fixture
def seed_file(tmp_path: Path) -> Path:
    path = tmp_path / "seed.jsonl"
    rows = [feature(f"t{i}", minutes_ago=(10 - i) * 60, lon=-89.6 + i * 2, lat=39.8 + i) for i in range(10)]
    path.write_text("\n".join(json.dumps({"feature": f}) for f in rows), encoding="utf-8")
    return path


@pytest.fixture
def world(conn: psycopg.Connection[Any]) -> psycopg.Connection[Any]:
    seed_places(conn)
    reset_events(conn)
    conn.execute("DELETE FROM users WHERE email LIKE 'demo-%'")
    conn.execute("DELETE FROM tenants WHERE slug = 'demo'")
    conn.commit()
    return conn


def test_retime_puts_the_newest_record_one_minute_before_the_anchor(seed_file: Path) -> None:
    shifted = replay.retime(replay.load(seed_file), ANCHOR)
    times = [f["properties"]["time"] for f in shifted]
    assert times == sorted(times)
    assert max(times) == int((ANCHOR - dt.timedelta(minutes=1)).timestamp() * 1000)
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert set(gaps) == {3_600_000}  # the spacing between records is preserved


def test_replay_loads_history_at_once_and_paces_the_rest(world: psycopg.Connection[Any], seed_file: Path) -> None:
    waits: list[float] = []
    result = replay.run(
        world, CFG, seed_file, speed=1800, max_wait=2.0, preload=0.7, sleep=waits.append, now=dt.datetime.now(dt.UTC)
    )
    assert result["records"] == 10 and result["loaded_as_history"] == 7 and result["played_live"] == 3
    assert result["actions"] == {"created": 10}
    assert len(waits) == 3 and all(w == 2.0 for w in waits)  # one hour apart divided by 1800 is 2 s, the cap
    summary = world.execute("SELECT summary FROM events WHERE summary IS NOT NULL LIMIT 1").fetchone()
    assert summary is not None and summary[0].startswith(replay.NOTE)


def test_replaying_twice_revises_instead_of_duplicating(world: psycopg.Connection[Any], seed_file: Path) -> None:
    replay.run(world, CFG, seed_file, preload=1.0, sleep=lambda _: None)
    again = replay.run(world, CFG, seed_file, preload=1.0, sleep=lambda _: None)
    assert again["actions"] == {"revised": 10}
    assert world.execute("SELECT count(*) FROM events").fetchone() == (10,)


def test_demo_accounts_are_issued_once_and_stored_hashed(world: psycopg.Connection[Any]) -> None:
    issued = demo.seed_accounts(world)
    assert len(issued) == 6 and set(issued) == {demo.email_for(a[0]) for a in demo.ACCOUNTS}
    rows = dict(world.execute("SELECT email, password_hash FROM users WHERE email LIKE 'demo-%'").fetchall())
    for email, password in issued.items():
        assert password not in rows[email] and rows[email].startswith("$argon2id$")
        assert passwords.verify_password(rows[email], password)
    roles = dict(world.execute("SELECT email, role FROM users WHERE email LIKE 'demo-%'").fetchall())
    assert roles[demo.email_for("viewer")] == "viewer" and roles[demo.email_for("platform")] == "platform_admin"
    assert world.execute("SELECT tenant_id FROM users WHERE email = %s", (demo.email_for("platform"),)).fetchone() == (
        None,
    )

    assert demo.seed_accounts(world) == {}  # a second run neither changes nor reveals anything
    assert passwords.verify_password(rows[demo.email_for("viewer")], issued[demo.email_for("viewer")])

    rotated = demo.seed_accounts(world, rotate=True)
    assert set(rotated) == set(issued) and all(rotated[e] != issued[e] for e in issued)
    new_hash = world.execute("SELECT password_hash FROM users WHERE email = %s", (demo.email_for("viewer"),)).fetchone()
    assert new_hash is not None and passwords.verify_password(new_hash[0], rotated[demo.email_for("viewer")])


def test_generated_passwords_are_long_and_random() -> None:
    values = {demo.generate_password() for _ in range(50)}
    assert len(values) == 50 and all(len(v) == 24 and v.count("-") == 4 for v in values)


def test_demo_assets_are_illustrative_and_land_near_severe_incidents(world: psycopg.Connection[Any]) -> None:
    make_event(world, lat=39.8, lon=-89.6, severity=4, uncertainty=15.0)
    demo.seed_accounts(world)
    created = demo.seed_assets(world, 20)
    assert created > 0
    names = [
        r[0]
        for r in world.execute("SELECT a.name FROM assets a JOIN tenants t ON t.id = a.tenant_id WHERE t.slug = 'demo'")
    ]
    assert len(names) == created and all(n.endswith("(illustrative)") for n in names)
    assert demo.seed_assets(world, 20) == 0  # does not add a second portfolio
    result = demo.refresh_exposures(world)
    assert result["events"] == 1
