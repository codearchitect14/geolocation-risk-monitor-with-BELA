"""Exit criterion: a news article about a plant fire in an ambiguously named town and a USGS record both create events at the
right places, merge when appropriate, and alert the nearest asset but not the same-name decoy."""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
import pytest

from meridian.events import alerts, exposure, service
from meridian.events.config import load_events_config
from meridian.events.ingest import EventIngestor
from meridian.events.news import Article, NewsIngestor
from meridian.events.normalizers import usgs
from meridian.linking.pipeline import LinkingPipeline, Stages
from meridian.linking.reranker import Reranker
from tests.events_support import NOW, FakeNel, fake_embedder, llm_returning, reset_events, seed_places, seed_tenant

CFG = load_events_config()

FIRE_TEXT = (
    "A fire broke out on Sunday at the Prairie Chemicals plant in Springfield, Illinois. Residents near the factory were "
    "asked to keep windows closed while crews worked to contain the blaze. Illinois officials said no injuries were reported."
)
FIRE_TEXT_2 = (
    "Firefighters battled a large blaze at a chemical plant in Springfield, Illinois on Sunday, officials said."
)


def pipeline_for(conn: psycopg.Connection[Any]) -> LinkingPipeline:
    return LinkingPipeline(conn, FakeNel(), reranker=Reranker(None, "rules_v1"))


@pytest.fixture
def world(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    seed_places(conn)
    reset_events(conn)
    tenant, assets = seed_tenant(
        conn, [("IL plant", 39.78, -89.60, 5), ("MO decoy", 37.20, -93.28, 5), ("Dayton depot", 39.76, -84.20, 4)]
    )
    return {"conn": conn, "tenant": tenant, "assets": assets}


def news_ingestor(conn: psycopg.Connection[Any], **label: Any) -> NewsIngestor:
    return NewsIngestor(
        conn,
        CFG,
        pipeline_for(conn),
        llm_returning(**label),
        EventIngestor(conn, CFG, fake_embedder),
        Stages(llm=False),
    )


def article(url: str, title: str, text: str, hours: float = 0) -> Article:
    return Article(url, title, text, NOW + dt.timedelta(hours=hours), lang="en", outlet_country="US")


def alerted_assets(conn: psycopg.Connection[Any], event_id: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT a.name FROM alerts x JOIN assets a ON a.id = x.asset_id WHERE x.event_id = %s", (event_id,))
        return {r[0] for r in cur.fetchall()}


def test_fire_in_springfield_alerts_the_illinois_plant_and_not_the_missouri_decoy(world: dict[str, Any]) -> None:
    conn = world["conn"]
    ingest = news_ingestor(conn)
    first = ingest.process(
        article("https://www.statejournal.example/fire", "Fire at chemical plant in Springfield, Illinois", FIRE_TEXT)
    )
    assert first.status == "event" and first.outcome is not None and first.outcome.action == "created"
    event_id = first.outcome.event_id
    with conn.cursor() as cur:
        cur.execute("SELECT ST_Y(geom), ST_X(geom), type, subtype, confirmation FROM events WHERE id = %s", (event_id,))
        lat, lon, type_, subtype, confirmation = cur.fetchone()  # type: ignore[misc]
    assert (round(lat, 2), round(lon, 2)) == (39.80, -89.64)  # Springfield, Illinois, not Springfield, Missouri
    assert (type_, subtype, confirmation) == ("industrial_accident", "fire", "unconfirmed")

    service.process_event(conn, CFG, event_id, NOW)
    conn.commit()
    assert alerted_assets(conn, event_id) == {"IL plant"}


def test_second_outlet_merges_and_confirms(world: dict[str, Any]) -> None:
    conn = world["conn"]
    ingest = news_ingestor(conn)
    a = ingest.process(
        article("https://www.statejournal.example/fire", "Fire at chemical plant in Springfield, Illinois", FIRE_TEXT)
    )
    b = ingest.process(
        article(
            "https://news.regional.example/blaze", "Chemical plant fire in Springfield, Illinois", FIRE_TEXT_2, hours=2
        )
    )
    assert a.outcome is not None and b.outcome is not None
    assert b.outcome.action == "merged" and b.outcome.event_id == a.outcome.event_id
    with conn.cursor() as cur:
        cur.execute(
            "SELECT confirmation, reliability, (SELECT count(*) FROM events) FROM events WHERE id = %s",
            (a.outcome.event_id,),
        )
        confirmation, reliability, total = cur.fetchone()  # type: ignore[misc]
    assert confirmation == "confirmed" and reliability > 0.6 and total == 1


def test_same_report_twice_is_idempotent(world: dict[str, Any]) -> None:
    conn = world["conn"]
    ingest = news_ingestor(conn)
    item = article(
        "https://www.statejournal.example/fire", "Fire at chemical plant in Springfield, Illinois", FIRE_TEXT
    )
    ingest.process(item)
    assert ingest.process(item).status == "duplicate"
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM events")
        assert cur.fetchone() == (1,)


def test_usgs_quake_near_the_missouri_asset_alerts_only_that_asset(world: dict[str, Any]) -> None:
    conn = world["conn"]
    feature = {
        "id": "us7000test",
        "properties": {
            "mag": 6.2,
            "place": "5 km N of Springfield, Missouri",
            "time": int(NOW.timestamp() * 1000),
            "updated": int(NOW.timestamp() * 1000),
            "type": "earthquake",
            "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000test",
            "alert": None,
            "title": "M 6.2 - near Springfield",
        },
        "geometry": {"type": "Point", "coordinates": [-93.29, 37.26, 10.0]},
    }
    ne = usgs.normalize(feature, CFG)
    assert ne is not None
    outcome = EventIngestor(conn, CFG, fake_embedder).ingest(ne)
    service.process_event(conn, CFG, outcome.event_id, NOW)
    conn.commit()
    assert outcome.action == "created"
    assert alerted_assets(conn, outcome.event_id) == {"MO decoy"}


def test_fire_and_quake_stay_separate_events(world: dict[str, Any]) -> None:
    conn = world["conn"]
    fire = news_ingestor(conn).process(
        article("https://www.statejournal.example/fire", "Fire at chemical plant in Springfield, Illinois", FIRE_TEXT)
    )
    feature = {
        "id": "us7000test2",
        "properties": {
            "mag": 5.0,
            "time": int(NOW.timestamp() * 1000),
            "updated": int(NOW.timestamp() * 1000),
            "type": "earthquake",
            "title": "M 5.0",
        },
        "geometry": {"type": "Point", "coordinates": [-93.29, 37.26, 10.0]},
    }
    ne = usgs.normalize(feature, CFG)
    assert ne is not None and fire.outcome is not None
    quake = EventIngestor(conn, CFG, fake_embedder).ingest(ne)
    assert quake.action == "created" and quake.event_id != fire.outcome.event_id


def test_report_about_a_named_private_person_is_dropped_without_an_event(world: dict[str, Any]) -> None:
    conn = world["conn"]
    result = news_ingestor(conn, subject_is_named_private_person=True).process(
        article("https://www.statejournal.example/person", "Neighbor John Smith hurt in fire", FIRE_TEXT)
    )
    assert result.status == "dropped_private_person" and result.outcome is None
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM events")
        assert cur.fetchone() == (0,)
        cur.execute("SELECT status FROM articles")
        assert cur.fetchone() == ("dropped_private_person",)


def test_report_that_is_not_a_disruption_is_dropped(world: dict[str, Any]) -> None:
    result = news_ingestor(world["conn"], event_type="none", subtype="other", severity=1).process(
        article(
            "https://www.statejournal.example/fair",
            "County fair opens in Springfield",
            "The fair opens Friday in Springfield, Illinois.",
        )
    )
    assert result.status == "dropped_not_a_disruption" and result.outcome is None


def test_article_without_a_place_creates_no_event(world: dict[str, Any]) -> None:
    result = news_ingestor(world["conn"]).process(
        article(
            "https://www.statejournal.example/nowhere",
            "Fire at plant",
            "A fire broke out at a plant on Sunday and crews responded.",
        )
    )
    assert result.status == "no_location" and result.outcome is None


def test_stored_snippet_is_at_most_300_characters_and_mentions_are_kept(world: dict[str, Any]) -> None:
    conn = world["conn"]
    news_ingestor(conn).process(
        article("https://www.statejournal.example/long", "Fire in Springfield", FIRE_TEXT + " More detail. " * 60)
    )
    with conn.cursor() as cur:
        cur.execute("SELECT length(snippet) FROM articles")
        assert cur.fetchone()[0] <= 300  # type: ignore[index]
        cur.execute("SELECT count(*) FROM mentions")
        assert cur.fetchone()[0] >= 1  # type: ignore[index]
        cur.execute("SELECT count(*) FROM mention_candidates")
        assert cur.fetchone()[0] >= 2  # type: ignore[index]


def test_alerts_and_exposure_components_are_visible(world: dict[str, Any]) -> None:
    conn = world["conn"]
    result = news_ingestor(conn).process(
        article("https://www.statejournal.example/fire", "Fire at chemical plant in Springfield, Illinois", FIRE_TEXT)
    )
    assert result.outcome is not None
    exposure.compute_for_event(conn, CFG, result.outcome.event_id, NOW)
    alerts.evaluate_alerts(conn, CFG, result.outcome.event_id, NOW)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT components FROM exposures x JOIN assets a ON a.id = x.asset_id WHERE a.name = 'IL plant'")
        components = cur.fetchone()[0]  # type: ignore[index]
    for key in (
        "type_weight",
        "severity_weight",
        "proximity",
        "location_confidence",
        "source_reliability",
        "recency_decay",
        "criticality_factor",
    ):
        assert key in components


def test_article_dated_in_the_future_is_rejected(world: dict[str, Any]) -> None:
    result = news_ingestor(world["conn"]).process(
        article("https://www.statejournal.example/future", "Fire in Springfield, Illinois", FIRE_TEXT, hours=24 * 30)
    )
    assert result.status == "invalid_date" and result.outcome is None
