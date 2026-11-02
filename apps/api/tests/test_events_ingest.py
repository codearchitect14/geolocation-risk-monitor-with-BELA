"""Creating, revising, superseding, and merging events."""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
import pytest

from meridian.events import status
from meridian.events.config import load_events_config
from meridian.events.ingest import EventIngestor, allowed_distance_km, compatible
from meridian.events.normalizers import usgs
from meridian.events.types import NormalizedEvent
from tests.events_support import NOW, fake_embedder, reset_events

CFG = load_events_config()


@pytest.fixture
def ingestor(conn: psycopg.Connection[Any]) -> EventIngestor:
    reset_events(conn)
    return EventIngestor(conn, CFG, fake_embedder)


def news(
    ref: str,
    title: str,
    lat: float,
    lon: float,
    *,
    domain: str,
    type_: str = "industrial_accident",
    subtype: str | None = "fire",
    severity: int = 3,
    hours: float = 0,
    uncertainty: float = 25,
    confidence: float = 0.8,
    level: str = "city",
) -> NormalizedEvent:
    when = NOW + dt.timedelta(hours=hours)
    return NormalizedEvent(
        "news",
        ref,
        type_,
        subtype,
        severity,
        title,
        {"type": "Point", "coordinates": [lon, lat]},
        level,
        uncertainty,
        when,
        when,
        url=f"https://{domain}/{ref}",
        domain=domain,
        location_confidence=confidence,
        language="en",
    )


def quake(
    ref: str = "us1",
    magnitude: float = 5.8,
    lat: float = 37.2,
    lon: float = -93.3,
    hours: float = 0,
    updated_hours: float = 0,
) -> NormalizedEvent:
    when = NOW + dt.timedelta(hours=hours)
    feature = {
        "id": ref,
        "geometry": {"type": "Point", "coordinates": [lon, lat, 10]},
        "properties": {
            "mag": magnitude,
            "place": "near Springfield",
            "time": int(when.timestamp() * 1000),
            "updated": int((NOW + dt.timedelta(hours=updated_hours)).timestamp() * 1000),
            "type": "earthquake",
            "title": f"M {magnitude} - near Springfield, Missouri",
        },
    }
    event = usgs.normalize(feature, CFG)
    assert event is not None
    return event


def row(conn: psycopg.Connection[Any], event_id: str, columns: str) -> tuple[Any, ...]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {columns} FROM events WHERE id = %s", (event_id,))  # noqa: S608
        found = cur.fetchone()
    assert found is not None
    return found


def count(conn: psycopg.Connection[Any], table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
        found = cur.fetchone()
    assert found is not None
    return int(found[0])


def test_new_record_creates_event_and_source(ingestor: EventIngestor, conn: psycopg.Connection[Any]) -> None:
    outcome = ingestor.ingest(quake())
    assert outcome.action == "created"
    typ, subtype, severity, status_, confirmation, reliability, cell = row(
        conn, outcome.event_id, "type, subtype, severity, status, confirmation, reliability, h3_cell"
    )
    assert (typ, subtype, severity, status_, confirmation) == ("natural_hazard", "earthquake", 3, "new", "unconfirmed")
    assert reliability == pytest.approx(0.95) and cell is not None
    assert count(conn, "event_sources") == 1


def test_same_record_twice_is_idempotent(ingestor: EventIngestor, conn: psycopg.Connection[Any]) -> None:
    first = ingestor.ingest(quake())
    again = ingestor.ingest(quake())
    assert again.action == "duplicate" and again.event_id == first.event_id
    assert count(conn, "events") == 1 and count(conn, "event_sources") == 1


def test_newer_revision_updates_severity_and_is_recorded(
    ingestor: EventIngestor, conn: psycopg.Connection[Any]
) -> None:
    created = ingestor.ingest(quake(magnitude=5.2, updated_hours=0))
    revised = ingestor.ingest(quake(magnitude=6.6, updated_hours=2))
    assert revised.action == "revised" and revised.event_id == created.event_id
    assert revised.detail == {"severity_before": 2, "severity_after": 4}
    assert row(conn, created.event_id, "severity")[0] == 4
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM event_updates WHERE event_id = %s AND update_type = 'revision'", (created.event_id,)
        )
        assert cur.fetchone() == (1,)


def test_two_earthquakes_from_the_feed_stay_separate(ingestor: EventIngestor, conn: psycopg.Connection[Any]) -> None:
    ingestor.ingest(quake("us1", 5.8))
    second = ingestor.ingest(quake("us2", 4.9, lat=37.25, lon=-93.31, hours=3))  # an aftershock a few km away
    assert second.action == "created" and count(conn, "events") == 2


def test_two_reports_of_one_fire_merge_and_become_confirmed(
    ingestor: EventIngestor, conn: psycopg.Connection[Any]
) -> None:
    first = ingestor.ingest(
        news("a", "Fire at chemical plant in Springfield injures two workers", 39.80, -89.64, domain="tribune.example")
    )
    second = ingestor.ingest(
        news(
            "b",
            "Two workers injured in chemical plant fire in Springfield",
            39.82,
            -89.60,
            domain="register.example",
            hours=3,
        )
    )
    assert second.action == "merged" and second.event_id == first.event_id
    assert second.detail["confirmation"] == "confirmed"
    assert count(conn, "events") == 1 and count(conn, "event_sources") == 2
    reliability, confirmation, status_ = row(conn, first.event_id, "reliability, confirmation, status")
    assert reliability == pytest.approx(0.84, abs=0.01) and confirmation == "confirmed" and status_ == "developing"


def test_second_report_from_the_same_outlet_does_not_confirm(
    ingestor: EventIngestor, conn: psycopg.Connection[Any]
) -> None:
    ingestor.ingest(
        news("a", "Fire at chemical plant in Springfield injures two workers", 39.80, -89.64, domain="tribune.example")
    )
    again = ingestor.ingest(
        news(
            "b",
            "Fire at chemical plant in Springfield injures two workers update",
            39.80,
            -89.64,
            domain="tribune.example",
            hours=2,
        )
    )
    assert again.action == "merged" and again.detail["confirmation"] == "unconfirmed"


def test_similar_title_in_another_place_or_another_time_is_a_different_event(
    ingestor: EventIngestor, conn: psycopg.Connection[Any]
) -> None:
    ingestor.ingest(
        news("a", "Fire at chemical plant in Springfield injures two workers", 39.80, -89.64, domain="tribune.example")
    )
    far = ingestor.ingest(
        news(
            "b",
            "Fire at chemical plant in Springfield injures two workers",
            37.22,
            -93.30,
            domain="news-leader.example",
            hours=1,
        )
    )
    late = ingestor.ingest(
        news(
            "c",
            "Fire at chemical plant in Springfield injures two workers",
            39.80,
            -89.64,
            domain="wsil.example",
            hours=24 * 5,
        )
    )
    assert far.action == "created" and late.action == "created"
    assert count(conn, "events") == 3


def test_unrelated_incident_at_the_same_place_is_not_merged(
    ingestor: EventIngestor, conn: psycopg.Connection[Any]
) -> None:
    ingestor.ingest(
        news("a", "Fire at chemical plant in Springfield injures two workers", 39.80, -89.64, domain="tribune.example")
    )
    other = ingestor.ingest(
        news(
            "b",
            "Council approves new budget for road repairs downtown",
            39.80,
            -89.64,
            domain="register.example",
            hours=1,
        )
    )
    assert other.action == "created"


def test_news_about_a_quake_joins_the_feed_event_and_the_feed_location_wins(
    ingestor: EventIngestor, conn: psycopg.Connection[Any]
) -> None:
    created = ingestor.ingest(quake("us1", 5.8, lat=37.20, lon=-93.28))
    merged = ingestor.ingest(
        news(
            "a",
            "Strong earthquake shakes Springfield",
            37.22,
            -93.30,
            domain="news-leader.example",
            type_="natural_hazard",
            subtype="earthquake",
            severity=3,
            hours=1,
            uncertainty=25,
            confidence=0.9,
        )
    )
    assert merged.action == "merged" and merged.event_id == created.event_id
    assert merged.detail["location_replaced"] is False
    uncertainty, source, confirmation = row(
        conn, created.event_id, "uncertainty_km, details->>'location_source', confirmation"
    )
    assert uncertainty == 10 and source == "usgs" and confirmation == "confirmed"


def test_news_first_then_feed_adopts_the_feed_location(ingestor: EventIngestor, conn: psycopg.Connection[Any]) -> None:
    created = ingestor.ingest(
        news(
            "a",
            "Strong earthquake shakes Springfield",
            37.22,
            -93.30,
            domain="news-leader.example",
            type_="natural_hazard",
            subtype="earthquake",
            severity=2,
            uncertainty=25,
        )
    )
    merged = ingestor.ingest(quake("us1", 5.8, lat=37.20, lon=-93.28, hours=1))
    assert (
        merged.action == "merged" and merged.event_id == created.event_id and merged.detail["location_replaced"] is True
    )
    severity, source = row(conn, created.event_id, "severity, details->>'location_source'")
    assert severity == 3 and source == "usgs"


def test_fire_news_joins_a_satellite_fire_cluster_but_not_an_earthquake(
    ingestor: EventIngestor, conn: psycopg.Connection[Any]
) -> None:
    fire = NormalizedEvent(
        "firms",
        "cell:20261102",
        "natural_hazard",
        "wildfire",
        3,
        "Active fire near Springfield",
        {"type": "Point", "coordinates": [-89.64, 39.80]},
        "natural",
        3,
        NOW,
        NOW,
    )
    created = ingestor.ingest(fire)
    joined = ingestor.ingest(news("a", "Wildfire burns near Springfield", 39.80, -89.64, domain="x.example", hours=1))
    assert joined.event_id == created.event_id
    quake_event = ingestor.ingest(quake("us9", 5.0, lat=39.80, lon=-89.64, hours=1))
    assert quake_event.event_id != created.event_id


def test_nws_update_joins_the_original_alert_and_a_cancel_resolves_it(
    ingestor: EventIngestor, conn: psycopg.Connection[Any]
) -> None:
    square = {
        "type": "Polygon",
        "coordinates": [[[-96.7, 39.6], [-96.5, 39.6], [-96.5, 39.8], [-96.7, 39.8], [-96.7, 39.6]]],
    }

    def alert(ref: str, severity: int, supersedes: list[str], hours: float, cancelled: bool = False) -> NormalizedEvent:
        when = NOW + dt.timedelta(hours=hours)
        return NormalizedEvent(
            "nws",
            ref,
            "natural_hazard",
            "flood",
            severity,
            "Flood Warning",
            square,
            "admin2",
            0,
            when,
            when,
            supersedes=supersedes,
            details={"cancelled": cancelled},
            expires_at=when + dt.timedelta(hours=12),
        )

    first = ingestor.ingest(alert("urn:1", 2, [], 0))
    update = ingestor.ingest(alert("urn:2", 3, ["urn:1"], 2))
    assert update.action == "superseded" and update.event_id == first.event_id
    assert row(conn, first.event_id, "severity")[0] == 3
    cancel = ingestor.ingest(alert("urn:3", 3, ["urn:2"], 4, cancelled=True))
    assert cancel.action == "cancelled" and row(conn, first.event_id, "status")[0] == "resolved"
    assert count(conn, "events") == 1


def test_compatibility_and_distance_rules() -> None:
    assert compatible(CFG, "industrial_accident", "fire", "natural_hazard", "wildfire")
    assert not compatible(CFG, "industrial_accident", "spill", "natural_hazard", "wildfire")
    assert not compatible(CFG, "labor_action", "strike", "natural_hazard", "flood")
    assert compatible(CFG, "natural_hazard", "flood", "natural_hazard", "storm")
    assert not compatible(CFG, "natural_hazard", "earthquake", "natural_hazard", "flood")
    assert allowed_distance_km(CFG, "industrial_accident", 0, 0) == 5
    assert allowed_distance_km(CFG, "industrial_accident", 25, 25) == 50
    assert allowed_distance_km(CFG, "natural_hazard", 500, 500) == 400


def test_status_lifecycle() -> None:
    first = NOW
    args = (CFG, "industrial_accident", first)
    assert status.status_for(*args, first, None, 1, 0, first + dt.timedelta(hours=1)) == "new"
    assert status.status_for(*args, first, None, 2, 0, first + dt.timedelta(hours=1)) == "developing"
    assert (
        status.status_for(*args, first + dt.timedelta(hours=8), None, 1, 1, first + dt.timedelta(hours=9)) == "ongoing"
    )
    assert (
        status.status_for(*args, first + dt.timedelta(hours=8), None, 1, 1, first + dt.timedelta(hours=40))
        == "resolved"
    )
    expiry = first + dt.timedelta(hours=6)
    assert (
        status.status_for(CFG, "natural_hazard", first, first, expiry, 1, 0, first + dt.timedelta(hours=8))
        == "resolved"
    )


def test_resolved_event_reopens_when_a_new_report_arrives(
    ingestor: EventIngestor, conn: psycopg.Connection[Any]
) -> None:
    created = ingestor.ingest(
        news("a", "Fire at chemical plant in Springfield injures two workers", 39.80, -89.64, domain="tribune.example")
    )
    resolved = status.refresh_all(conn, CFG, NOW + dt.timedelta(hours=30))
    assert resolved == {"resolved": 1} and row(conn, created.event_id, "status")[0] == "resolved"
    again = ingestor.ingest(
        news(
            "b",
            "Fire at chemical plant in Springfield injures two workers",
            39.80,
            -89.64,
            domain="register.example",
            hours=40,
        )
    )
    assert again.action == "merged" and row(conn, created.event_id, "status")[0] != "resolved"
