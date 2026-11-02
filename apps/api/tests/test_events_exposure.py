"""Exposure scoring: the formula, geometry cases, and the cases that must not be scored."""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

import psycopg
import pytest

from meridian.events import exposure
from meridian.events.config import load_events_config
from tests.events_support import NOW, make_event, reset_events, seed_tenant

CFG = load_events_config()
LAT, LON = 39.80, -89.64


def km_north(km: float) -> float:
    return LAT + km / 111.195


def stored(conn: psycopg.Connection[Any], event_id: str) -> dict[str, tuple[float, str, float, bool, dict[str, Any]]]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT a.name, x.score, x.level, x.distance_km, x.within_uncertainty, x.components
                 FROM exposures x JOIN assets a ON a.id = x.asset_id WHERE x.event_id = %s""",
            (event_id,),
        )
        return {r[0]: (float(r[1]), r[2], float(r[3]), r[4], r[5]) for r in cur.fetchall()}


@pytest.fixture
def clean(conn: psycopg.Connection[Any]) -> psycopg.Connection[Any]:
    reset_events(conn)
    return conn


def test_formula_matches_an_independent_calculation(clean: psycopg.Connection[Any]) -> None:
    seed_tenant(
        clean, [("at-center", LAT, LON, 5), ("30km-out", km_north(30), LON, 3), ("300km-out", km_north(300), LON, 3)]
    )
    event_id = make_event(clean, lat=LAT, lon=LON)
    exposure.compute_for_event(clean, CFG, event_id, NOW)
    rows = stored(clean, event_id)
    # fire, severity 3: 1.0 * 0.60 * proximity * 0.8 * 0.6 * recency 1 * criticality
    assert (
        rows["at-center"][0] == pytest.approx(1.0 * 0.60 * 1.0 * 0.8 * 0.6 * 1.0 * 1.4) and rows["at-center"][3] is True
    )
    decay = math.exp(-(rows["30km-out"][2] - 25.0) / 5.0)  # lambda 5 km for a fire
    assert rows["30km-out"][0] == pytest.approx(0.60 * decay * 0.8 * 0.6 * 1.0 * 1.0) and rows["30km-out"][3] is False
    assert "300km-out" not in rows  # far below the storage threshold
    components = rows["at-center"][4]
    assert components["lambda_km"] == 5 and components["half_life_hours"] == 24 and components["clamped"] is False
    assert components["raw_score"] == pytest.approx(rows["at-center"][0])


def test_levels_follow_the_thresholds(clean: psycopg.Connection[Any]) -> None:
    seed_tenant(clean, [("critical-site", LAT, LON, 5)])
    event_id = make_event(clean, lat=LAT, lon=LON, severity=4, confidence=1.0, reliability=0.9)
    exposure.compute_for_event(clean, CFG, event_id, NOW)
    score, level, *_ = stored(clean, event_id)["critical-site"]
    assert score == pytest.approx(0.85 * 1.0 * 0.9 * 1.4) or score == 1.0
    assert level == "critical"
    assert CFG.level_for(0.55) == "high" and CFG.level_for(0.35) == "medium" and CFG.level_for(0.1) == "low"


def test_score_is_clamped_to_one_and_the_raw_value_is_kept(clean: psycopg.Connection[Any]) -> None:
    seed_tenant(clean, [("s", LAT, LON, 5)])
    event_id = make_event(clean, lat=LAT, lon=LON, severity=4, confidence=1.0, reliability=0.99)
    exposure.compute_for_event(clean, CFG, event_id, NOW)
    score, _, _, _, components = stored(clean, event_id)["s"]
    assert (
        score == 1.0 and components["clamped"] is True and components["raw_score"] == pytest.approx(0.85 * 0.99 * 1.4)
    )


def test_polygon_and_route_assets(clean: psycopg.Connection[Any]) -> None:
    tenant, _ = seed_tenant(clean, [])
    with clean.cursor() as cur:
        cur.execute(
            """INSERT INTO assets (tenant_id, name, type, geom, criticality) VALUES
            (%(t)s, 'region', 'region', ST_GeomFromText('POLYGON((-90 39.5, -89 39.5, -89 40.2, -90 40.2, -90 39.5))', 4326), 3),
            (%(t)s, 'route', 'route', ST_GeomFromText('LINESTRING(-89.9 39.9, -89.4 39.9)', 4326), 5),
            (%(t)s, 'far-route', 'route', ST_GeomFromText('LINESTRING(-89.9 41.5, -89.4 41.5)', 4326), 3)""",
            {"t": tenant},
        )
    clean.commit()
    event_id = make_event(clean, lat=LAT, lon=LON, uncertainty=2.0, level="facility")
    exposure.compute_for_event(clean, CFG, event_id, NOW)
    rows = stored(clean, event_id)
    assert rows["region"][2] == 0 and rows["region"][3] is True  # the polygon contains the event point
    assert 9 < rows["route"][2] < 13 and rows["route"][3] is False  # distance to the nearest point of the line
    assert "far-route" not in rows
    assert rows["route"][0] == pytest.approx(0.60 * math.exp(-(rows["route"][2] - 2.0) / 5.0) * 0.8 * 0.6 * 1.4)


def test_polygon_event_scores_assets_inside_it_at_full_proximity(clean: psycopg.Connection[Any]) -> None:
    seed_tenant(clean, [("inside", 39.7, -96.6, 3), ("outside", 39.7, -95.0, 3)])
    zone = {
        "type": "Polygon",
        "coordinates": [[[-96.7, 39.6], [-96.5, 39.6], [-96.5, 39.8], [-96.7, 39.8], [-96.7, 39.6]]],
    }
    event_id = make_event(
        clean,
        lat=39.7,
        lon=-96.6,
        type_="natural_hazard",
        subtype="flood",
        uncertainty=0,
        level="admin2",
        geometry=zone,
    )
    exposure.compute_for_event(clean, CFG, event_id, NOW)
    rows = stored(clean, event_id)
    assert rows["inside"][2] == 0 and rows["inside"][4]["proximity"] == 1.0 and "outside" not in rows


def test_country_level_and_resolved_events_are_not_matched(clean: psycopg.Connection[Any]) -> None:
    seed_tenant(clean, [("s", LAT, LON, 5)])
    country = make_event(clean, lat=LAT, lon=LON, level="country", uncertainty=300)
    resolved = make_event(clean, lat=LAT, lon=LON, status="resolved")
    assert exposure.compute_for_event(clean, CFG, country, NOW) == []
    assert exposure.compute_for_event(clean, CFG, resolved, NOW) == []
    assert stored(clean, country) == {} and stored(clean, resolved) == {}


def test_recency_halves_the_score_per_half_life(clean: psycopg.Connection[Any]) -> None:
    seed_tenant(clean, [("s", LAT, LON, 5)])
    fire = make_event(clean, lat=LAT, lon=LON)
    flood = make_event(clean, lat=LAT, lon=LON, type_="natural_hazard", subtype="flood", uncertainty=25.0)
    exposure.compute_for_event(clean, CFG, fire, NOW)
    exposure.compute_for_event(clean, CFG, flood, NOW)
    fresh_fire, fresh_flood = stored(clean, fire)["s"][0], stored(clean, flood)["s"][0]
    exposure.compute_for_event(clean, CFG, fire, NOW + dt.timedelta(hours=24))
    exposure.compute_for_event(clean, CFG, flood, NOW + dt.timedelta(hours=24))
    assert stored(clean, fire)["s"][0] == pytest.approx(fresh_fire / 2)  # fast event: half-life 24 h
    assert stored(clean, flood)["s"][0] == pytest.approx(fresh_flood * 0.5 ** (24 / 72))  # slow event: half-life 72 h


def test_earthquake_decay_depends_on_magnitude(clean: psycopg.Connection[Any]) -> None:
    seed_tenant(clean, [("250km", km_north(250), LON, 3)])
    small = make_event(
        clean,
        lat=LAT,
        lon=LON,
        type_="natural_hazard",
        subtype="earthquake",
        severity=4,
        uncertainty=10,
        level="natural",
        confidence=1.0,
        reliability=0.95,
        details={"magnitude": 5.0},
    )
    big = make_event(
        clean,
        lat=LAT,
        lon=LON,
        type_="natural_hazard",
        subtype="earthquake",
        severity=4,
        uncertainty=10,
        level="natural",
        confidence=1.0,
        reliability=0.95,
        details={"magnitude": 6.8},
    )
    exposure.compute_for_event(clean, CFG, small, NOW)
    exposure.compute_for_event(clean, CFG, big, NOW)
    assert stored(clean, small) == {}  # lambda 30 km: nothing left at 300 km
    d = stored(clean, big)["250km"][2]
    assert stored(clean, big)["250km"][0] == pytest.approx(0.85 * math.exp(-(d - 10) / 100) * 0.95)


def test_recomputing_replaces_and_removes_exposures(clean: psycopg.Connection[Any]) -> None:
    _, assets = seed_tenant(clean, [("a", LAT, LON, 3)])
    event_id = make_event(clean, lat=LAT, lon=LON)
    exposure.compute_for_event(clean, CFG, event_id, NOW)
    exposure.compute_for_event(clean, CFG, event_id, NOW)
    assert len(stored(clean, event_id)) == 1  # the unique pair is upserted, not duplicated
    with clean.cursor() as cur:
        cur.execute("UPDATE assets SET status = 'archived' WHERE id = %s", (assets["a"],))
    clean.commit()
    exposure.compute_for_event(clean, CFG, event_id, NOW)
    assert stored(clean, event_id) == {}


def test_tenant_filter_limits_the_computation(clean: psycopg.Connection[Any]) -> None:
    t1, _ = seed_tenant(clean, [("one", LAT, LON, 3)], name="Tenant One")
    seed_tenant(clean, [("two", LAT, LON, 3)], name="Tenant Two")
    event_id = make_event(clean, lat=LAT, lon=LON)
    exposure.compute_for_event(clean, CFG, event_id, NOW, tenant_id=t1)
    assert set(stored(clean, event_id)) == {"one"}
