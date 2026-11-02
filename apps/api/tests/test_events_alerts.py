"""Alert creation, de-duplication, updates, suppression, and watch zones."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import psycopg
import pytest

from meridian.events import alerts, exposure
from meridian.events.config import load_events_config
from tests.events_support import NOW, make_event, reset_events, seed_tenant

CFG = load_events_config()
LAT, LON = 39.80, -89.64


@pytest.fixture
def world(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    reset_events(conn)
    tenant, assets = seed_tenant(conn, [("site", LAT, LON, 5)])
    return {"conn": conn, "tenant": tenant, "asset": assets["site"]}


def run(conn: psycopg.Connection[Any], event_id: str, when: dt.datetime = NOW) -> alerts.AlertResult:
    exposure.compute_for_event(conn, CFG, event_id, when)
    result = alerts.evaluate_alerts(conn, CFG, event_id, when)
    conn.commit()
    return result


def set_event(conn: psycopg.Connection[Any], event_id: str, **fields: Any) -> None:
    with conn.cursor() as cur:
        for name, value in fields.items():
            cur.execute(f"UPDATE events SET {name} = %s WHERE id = %s", (value, event_id))  # noqa: S608
    conn.commit()


def alert_rows(conn: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute("SELECT level, status, last_score, asset_id, zone_id FROM alerts ORDER BY created_at")
        return cur.fetchall()


def event_kinds(conn: psycopg.Connection[Any]) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT kind FROM alert_events ORDER BY id")
        return [r[0] for r in cur.fetchall()]


def test_default_rule_alerts_from_medium_and_up(world: dict[str, Any]) -> None:
    conn = world["conn"]
    low = make_event(conn, lat=LAT, lon=LON, severity=1)  # 0.15 * 0.8 * 0.6 * 1.4 = 0.10: low
    assert run(conn, low).created == 0 and alert_rows(conn) == []
    medium = make_event(conn, lat=LAT, lon=LON, severity=3)  # 0.40: medium
    result = run(conn, medium)
    assert result.created == 1
    level, status, score, asset_id, zone_id = alert_rows(conn)[0]
    assert (level, status, str(asset_id), zone_id) == (
        "medium",
        "new",
        world["asset"],
        None,
    ) and score == pytest.approx(0.4032)
    assert event_kinds(conn) == ["created"]


def test_the_same_exposure_does_not_create_a_second_alert(world: dict[str, Any]) -> None:
    conn = world["conn"]
    event_id = make_event(conn, lat=LAT, lon=LON)
    run(conn, event_id)
    again = run(conn, event_id)
    assert (
        again.created == 0 and again.unchanged == 1 and len(alert_rows(conn)) == 1 and event_kinds(conn) == ["created"]
    )


def test_a_rising_level_updates_the_alert_and_a_small_change_does_not(world: dict[str, Any]) -> None:
    conn = world["conn"]
    event_id = make_event(conn, lat=LAT, lon=LON)  # medium
    run(conn, event_id)
    set_event(conn, event_id, reliability=0.65)  # 0.4368: still medium and +0.03: details only
    assert run(conn, event_id).updated == 0
    set_event(conn, event_id, reliability=0.95)  # 0.638: high
    result = run(conn, event_id)
    assert result.updated == 1 and alert_rows(conn)[0][0] == "high" and event_kinds(conn) == ["created", "update"]
    with conn.cursor() as cur:
        cur.execute("SELECT detail->>'previous_level' FROM alert_events WHERE kind = 'update'")
        assert cur.fetchone() == ("medium",)


def test_a_score_rise_of_ten_points_updates_within_a_level(world: dict[str, Any]) -> None:
    conn = world["conn"]
    event_id = make_event(conn, lat=LAT, lon=LON, reliability=0.6, confidence=0.6)  # 0.302: medium
    run(conn, event_id)
    set_event(conn, event_id, location_confidence=0.9)  # 0.453: still medium, +0.15
    assert run(conn, event_id).updated == 1


def test_tenant_rules_filter_by_type_severity_and_level(world: dict[str, Any]) -> None:
    conn = world["conn"]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO alert_rules (tenant_id, name, event_types, min_severity, min_level) VALUES (%s, 'fires only', %s, 3, 'low')",
            (world["tenant"], ["industrial_accident"]),
        )
        cur.execute(
            "INSERT INTO alert_rules (tenant_id, name, event_types, enabled) VALUES (%s, 'disabled', %s, false)",
            (world["tenant"], ["natural_hazard"]),
        )
    conn.commit()
    flood = make_event(conn, lat=LAT, lon=LON, type_="natural_hazard", subtype="flood", severity=4)
    fire_minor = make_event(conn, lat=LAT, lon=LON, severity=2)
    fire = make_event(conn, lat=LAT, lon=LON, severity=3, reliability=0.3)  # low level but allowed by the rule
    assert run(conn, flood).created == 0 and run(conn, fire_minor).created == 0
    assert run(conn, fire).created == 1 and alert_rows(conn)[0][0] == "low"


def test_subtype_can_be_used_in_a_rule(world: dict[str, Any]) -> None:
    conn = world["conn"]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO alert_rules (tenant_id, name, event_types, min_level) VALUES (%s, 'quakes', %s, 'low')",
            (world["tenant"], ["earthquake"]),
        )
    conn.commit()
    quake = make_event(
        conn,
        lat=LAT,
        lon=LON,
        type_="natural_hazard",
        subtype="earthquake",
        severity=4,
        uncertainty=10,
        details={"magnitude": 6.8},
    )
    assert run(conn, quake).created == 1


def test_asset_group_filter(world: dict[str, Any]) -> None:
    conn = world["conn"]
    with conn.cursor() as cur:
        cur.execute("INSERT INTO asset_groups (tenant_id, name) VALUES (%s, 'ports') RETURNING id", (world["tenant"],))
        group = str(cur.fetchone()[0])  # type: ignore[index]
        cur.execute(
            "INSERT INTO alert_rules (tenant_id, name, asset_group_ids, min_level) VALUES (%s, 'ports only', %s::uuid[], 'low')",
            (world["tenant"], [group]),
        )
    conn.commit()
    event_id = make_event(conn, lat=LAT, lon=LON)
    assert run(conn, event_id).created == 0  # the asset is not in the group
    with conn.cursor() as cur:
        cur.execute("INSERT INTO asset_group_members (group_id, asset_id) VALUES (%s, %s)", (group, world["asset"]))
    conn.commit()
    assert run(conn, event_id).created == 1


def test_assets_in_maintenance_get_no_alert(world: dict[str, Any]) -> None:
    conn = world["conn"]
    window = [{"start": (NOW - dt.timedelta(hours=1)).isoformat(), "end": (NOW + dt.timedelta(hours=5)).isoformat()}]
    with conn.cursor() as cur:
        cur.execute("UPDATE assets SET maintenance_windows = %s WHERE id = %s", (json.dumps(window), world["asset"]))
    conn.commit()
    event_id = make_event(conn, lat=LAT, lon=LON)
    result = run(conn, event_id)
    assert result.created == 0 and result.suppressed_maintenance == 1
    assert run(conn, event_id, NOW + dt.timedelta(hours=8)).created == 1  # after the window


def test_dismissed_alert_reopens_only_after_a_two_level_climb(world: dict[str, Any]) -> None:
    conn = world["conn"]
    event_id = make_event(conn, lat=LAT, lon=LON)  # medium
    run(conn, event_id)
    with conn.cursor() as cur:
        cur.execute("UPDATE alerts SET status = 'dismissed', dismissal_reason = 'known maintenance'")
    conn.commit()
    set_event(conn, event_id, reliability=0.95)  # high: one step
    assert run(conn, event_id).reopened == 0 and alert_rows(conn)[0][1] == "dismissed"
    set_event(conn, event_id, reliability=0.99, severity=4, location_confidence=1.0)  # critical: two steps from medium
    result = run(conn, event_id)
    assert result.reopened == 1 and alert_rows(conn)[0][1] == "new" and "status_change" in event_kinds(conn)


def test_country_level_events_do_not_alert(world: dict[str, Any]) -> None:
    conn = world["conn"]
    event_id = make_event(
        conn, lat=LAT, lon=LON, level="country", uncertainty=300, severity=4, reliability=0.99, confidence=1.0
    )
    assert run(conn, event_id).created == 0 and alert_rows(conn) == []


def test_watch_zone_raises_one_zone_alert_per_tenant(world: dict[str, Any]) -> None:
    conn = world["conn"]
    with conn.cursor() as cur:
        for name, rules in (
            ("zone a", {"min_severity": 3, "event_types": ["industrial_accident"], "min_level": "low"}),
            ("zone b", {}),
        ):
            cur.execute(
                "INSERT INTO watch_zones (tenant_id, name, geom, rules) VALUES (%s, %s, ST_GeomFromText('POLYGON((-91 39, -88 39, -88 41, -91 41, -91 39))', 4326), %s)",
                (world["tenant"], name, json.dumps(rules)),
            )
        cur.execute("DELETE FROM assets")
    conn.commit()
    event_id = make_event(conn, lat=LAT, lon=LON, severity=3, reliability=0.9)
    result = run(conn, event_id)
    assert result.zone_alerts == 1 and result.created == 1
    level, status, score, asset_id, zone_id = alert_rows(conn)[0]
    assert asset_id is None and zone_id is not None
    assert run(conn, event_id).created == 0  # a second evaluation does not duplicate it


def test_watch_zone_ignores_events_outside_it_and_events_below_its_rules(world: dict[str, Any]) -> None:
    conn = world["conn"]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO watch_zones (tenant_id, name, geom, rules) VALUES (%s, 'z', ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))', 4326), '{}')",
            (world["tenant"],),
        )
        cur.execute("DELETE FROM assets")
    conn.commit()
    assert run(conn, make_event(conn, lat=LAT, lon=LON, severity=4, reliability=0.99, confidence=1.0)).created == 0


def test_helper_functions() -> None:
    assert alerts.in_quiet_hours({"start": "22:00", "end": "06:00"}, dt.datetime(2026, 1, 1, 23, 30, tzinfo=dt.UTC))
    assert alerts.in_quiet_hours({"start": "22:00", "end": "06:00"}, dt.datetime(2026, 1, 1, 5, 59, tzinfo=dt.UTC))
    assert not alerts.in_quiet_hours({"start": "22:00", "end": "06:00"}, dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.UTC))
    assert not alerts.in_quiet_hours({}, NOW)
    assert alerts.rule_matches({"min_level": "medium"}, "industrial_accident", "fire", 1, "high", set())
    assert not alerts.rule_matches({"min_level": "high"}, "industrial_accident", "fire", 1, "medium", set())
    assert alerts.level_rank("critical") > alerts.level_rank("low")
