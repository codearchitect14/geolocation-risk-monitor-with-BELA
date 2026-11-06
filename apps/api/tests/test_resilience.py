"""Graceful degradation: the news path keeps working without the model server or the entity linker, says so, and parks what it
cannot process."""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx
import psycopg
import pytest

from meridian.events import resilience
from meridian.events.config import load_events_config
from meridian.events.ingest import EventIngestor
from meridian.events.news import Article, NewsIngestor, retry_dead_letters
from meridian.linking.nel_client import NelClient, NelMention
from meridian.linking.pipeline import LinkingPipeline
from meridian.linking.reranker import Reranker
from meridian.llm.client import LlmClient
from tests.events_support import NOW, FakeNel, fake_embedder, llm_returning, reset_events, seed_places

CFG = load_events_config()
TEXT = (
    "A fire broke out on Sunday at the Prairie Chemicals plant in Springfield, Illinois. Residents near the factory were "
    "asked to keep windows closed while crews worked to contain the blaze."
)


def down_llm() -> LlmClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    return LlmClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


class DownNel(NelClient):
    def __init__(self) -> None:
        pass

    def healthy(self) -> bool:
        return False

    def link(self, passages: list[tuple[str, str]], top_k: int = 10, batch: int = 32) -> dict[str, list[NelMention]]:
        raise httpx.ConnectError("connection refused")


def article(url: str, title: str, text: str = TEXT) -> Article:
    return Article(url, title, text, NOW, lang="en", outlet_country="US")


def ingestor(conn: psycopg.Connection[Any], llm: LlmClient, nel: NelClient) -> NewsIngestor:
    pipeline = LinkingPipeline(conn, nel, reranker=Reranker(None, "rules_v1"))
    return NewsIngestor(conn, CFG, pipeline, llm, EventIngestor(conn, CFG, fake_embedder), clock=lambda: NOW)


@pytest.fixture
def world(conn: psycopg.Connection[Any]) -> psycopg.Connection[Any]:
    seed_places(conn)
    reset_events(conn)
    conn.execute("DELETE FROM dead_letters")
    conn.commit()
    return conn


def reduced_flag(conn: psycopg.Connection[Any], event_id: str) -> bool:
    row = conn.execute("SELECT reduced_confidence FROM events WHERE id = %s", (event_id,)).fetchone()
    assert row is not None
    return bool(row[0])


def test_retry_call_backs_off_then_gives_up() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("refused")
        return "ok"

    assert resilience.retry_call(flaky, sleep=sleeps.append) == "ok"
    assert len(calls) == 3 and len(sleeps) == 2 and all(0 <= s <= 6 for s in sleeps)

    def always() -> str:
        raise httpx.ConnectError("refused")

    with pytest.raises(httpx.ConnectError):
        resilience.retry_call(always, attempts=2, sleep=sleeps.append)
    with pytest.raises(ValueError):  # not a transient error: no retry
        resilience.retry_call(lambda: (_ for _ in ()).throw(ValueError("bad")), sleep=sleeps.append)


def test_headline_rules_are_conservative() -> None:
    fire = resilience.rule_classify("Factory fire shuts down plant near Springfield")
    assert fire is not None and (fire.event_type, fire.subtype, fire.severity) == ("industrial_accident", "fire", 2)
    assert resilience.rule_classify("Dockworkers announce strike at Rotterdam terminal") is not None
    assert resilience.rule_classify("Local man, 34, dies in house fire") is None  # may name a private person
    assert resilience.rule_classify("Council approves new budget") is None


def test_health_probe_is_cached_and_can_be_marked_down() -> None:
    probes: list[int] = []

    class Target:
        def healthy(self) -> bool:
            probes.append(1)
            return True

    now = [0.0]
    health = resilience.DependencyHealth(Target(), None, clock=lambda: now[0])
    assert health.up("nel") and health.up("nel") and len(probes) == 1
    assert health.up("llm") is False  # not configured
    health.mark_down("nel")
    assert health.up("nel") is False and len(probes) == 1
    now[0] += resilience.HEALTH_TTL_SECONDS + 1
    assert health.up("nel") and len(probes) == 2


def test_model_server_down_uses_headline_rules_and_marks_the_event(world: psycopg.Connection[Any]) -> None:
    result = ingestor(world, down_llm(), FakeNel()).process(
        article("https://www.statejournal.example/a", "Fire at chemical plant in Springfield, Illinois")
    )
    assert result.status == "event" and result.outcome is not None
    assert result.degraded == ["llm"]
    assert reduced_flag(world, result.outcome.event_id)
    detail = world.execute("SELECT details FROM events WHERE id = %s", (result.outcome.event_id,)).fetchone()
    assert detail is not None and detail[0]["location_source"] == "news"


def test_entity_linker_down_falls_back_to_the_gazetteer(world: psycopg.Connection[Any]) -> None:
    result = ingestor(world, llm_returning(), DownNel()).process(
        article("https://www.statejournal.example/b", "Fire at chemical plant in Springfield, Illinois")
    )
    assert "nel" in result.degraded
    assert result.status in ("event", "no_location")  # located from capitalized place names, or honestly not located
    if result.outcome is not None:
        assert reduced_flag(world, result.outcome.event_id)


def test_healthy_services_do_not_set_the_flag(world: psycopg.Connection[Any]) -> None:
    result = ingestor(world, llm_returning(), FakeNel()).process(
        article("https://www.statejournal.example/c", "Fire at chemical plant in Springfield, Illinois")
    )
    assert result.outcome is not None and result.degraded == []
    assert not reduced_flag(world, result.outcome.event_id)


def test_unclassifiable_article_is_parked_without_its_text_and_retried(world: psycopg.Connection[Any]) -> None:
    url = "https://www.statejournal.example/d"
    parked = ingestor(world, down_llm(), FakeNel()).process(article(url, "Mayor speaks at council meeting"))
    assert parked.status == "queued"
    row = world.execute("SELECT status, attempts, payload::text FROM dead_letters").fetchone()
    assert row is not None and row[0] == "queued" and row[1] == 1
    assert "Prairie Chemicals" not in row[2] and "text" not in row[2].lower().replace("context", "")
    assert world.execute("SELECT count(*) FROM articles WHERE url = %s", (url,)).fetchone() == (0,)

    later = NOW + dt.timedelta(hours=1)
    fetched: list[str] = []

    def text_for(payload: dict[str, Any]) -> str | None:
        fetched.append(payload["url"])
        return TEXT

    healthy = ingestor(world, llm_returning(), FakeNel())
    counts = retry_dead_letters(healthy, text_for, later)
    assert counts["done"] == 1 and fetched == [url]
    assert world.execute("SELECT status FROM dead_letters").fetchone() == ("done",)
    assert retry_dead_letters(healthy, text_for, later) == {"done": 0, "requeued": 0, "abandoned": 0, "no_text": 0}


def test_backoff_grows_and_the_item_is_abandoned_after_the_last_attempt(world: psycopg.Connection[Any]) -> None:
    now = NOW
    resilience.enqueue(world, "article", "abc", {"url": "u"}, "down", now)
    still_down = ingestor(world, down_llm(), FakeNel())
    delays: list[float] = []
    for _ in range(resilience.MAX_ATTEMPTS):
        letters = resilience.due(world, "article", now + dt.timedelta(days=3))
        if not letters:
            break
        status = resilience.fail(world, letters[0], "still down", now)
        row = world.execute("SELECT next_attempt_at FROM dead_letters").fetchone()
        assert row is not None
        delays.append((row[0] - now).total_seconds())
        if status == "abandoned":
            break
    assert delays[:-1] == sorted(delays[:-1]) and delays[0] >= 300
    row = world.execute("SELECT status, attempts FROM dead_letters").fetchone()
    assert row == ("abandoned", resilience.MAX_ATTEMPTS)
    assert resilience.queue_depth(world) == {"abandoned": 1}
    assert still_down.health.up("llm") is False


def test_queue_depth_counts_by_status(world: psycopg.Connection[Any]) -> None:
    resilience.enqueue(world, "article", "q1", {"url": "u"}, "down", NOW)
    world.commit()
    assert resilience.queue_depth(world) == {"queued": 1}
