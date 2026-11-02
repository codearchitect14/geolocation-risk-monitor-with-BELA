"""The geo HTTP service end to end, with a fake entity linker and a small place table."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from geo_service import app as geo_app
from meridian.geo.names import normalize_name
from meridian.linking.nel_client import NelClient, NelMention
from meridian.linking.reranker import Reranker


class FakeNel(NelClient):
    def __init__(self) -> None:
        pass

    def healthy(self) -> bool:
        return True

    def link(self, passages: list[tuple[str, str]], top_k: int = 10, batch: int = 32) -> dict[str, list[NelMention]]:
        out: dict[str, list[NelMention]] = {}
        for pid, text in passages:
            start = text.find("Dayton")
            out[pid] = (
                [NelMention(start, start + 6, "Dayton", "Q3", 0.9, 0.95, [("Q3", 0.95)], [("Q3", 0.95)])]
                if start >= 0
                else []
            )
        return out


@pytest.fixture
def client(conn: psycopg.Connection[Any]) -> TestClient:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE places, ref_country_info CASCADE")
        cur.execute("INSERT INTO ref_country_info (iso2, iso3, name) VALUES ('US', 'USA', 'United States')")
        cur.execute(
            """INSERT INTO places (id, qid, name, name_normalized, type, country_code, population, lat, lon, centroid, geom,
                                   source, uncertainty_km, location_level)
               OVERRIDING SYSTEM VALUE VALUES (3, 'Q3', 'Dayton', %s, 'city', 'US', 137644, 39.76, -84.19,
                 ST_SetSRID(ST_MakePoint(-84.19, 39.76), 4326), ST_SetSRID(ST_MakePoint(-84.19, 39.76), 4326), 'wikidata', 25, 'city')""",
            (normalize_name("Dayton"),),
        )
    conn.commit()
    geo_app.state.nel = FakeNel()
    geo_app.state.llm = geo_app.LlmClient()
    geo_app.state.reranker = Reranker(None, "rules_v1")
    geo_app.state.calibrators = {}
    return TestClient(geo_app.app)


def test_gazetteer_search(client: TestClient) -> None:
    body = client.get("/v1/gazetteer/search", params={"q": "dayton"}).json()
    assert body["results"][0]["name"] == "Dayton" and body["results"][0]["uncertainty_km"] == 25


def test_locate_returns_places_event_location_and_disclaimer(client: TestClient) -> None:
    payload = {"title": "Fire at plant in Dayton", "text": "Crews responded to the blaze on Tuesday.", "use_llm": False}
    body = client.post("/v1/locate", json=payload).json()
    assert body["config_version"] == "geo_config_v1"
    assert body["mentions"][0]["place"]["name"] == "Dayton" and body["mentions"][0]["route"] == "accept"
    event = body["event_location"]
    assert event["level"] == "city" and event["alertable_against_sites"] is True and event["uncertainty_km"] == 25
    assert "not official warnings" in body["disclaimer"]


def test_locate_validates_input(client: TestClient) -> None:
    assert client.post("/v1/locate", json={"text": "x", "outlet_country": "usa"}).status_code == 422
    assert client.get("/v1/gazetteer/search", params={"q": ""}).status_code == 422
