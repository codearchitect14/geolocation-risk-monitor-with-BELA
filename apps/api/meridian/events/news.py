"""News article to event: classify, link places, choose the event location, store the evidence, and cluster.

Dropped before any event exists: reports about a named private person, and reports that are not disruptions. The article
row is kept either way with the reason, so the decision can be audited. Full article text is never stored, only a snippet
of at most 300 characters.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import psycopg

from meridian.events.classify import Classification, classify_report
from meridian.events.config import EventsConfig
from meridian.events.ingest import EventIngestor, Outcome
from meridian.events.types import NormalizedEvent
from meridian.linking.locate import LocateResult, locate
from meridian.linking.pipeline import LinkingPipeline, Stages
from meridian.llm.client import LlmClient


@dataclass
class Article:
    url: str
    title: str
    text: str
    published_at: dt.datetime
    lang: str | None = None
    outlet_country: str | None = None


@dataclass
class NewsResult:
    status: str  # event, dropped_private_person, dropped_not_a_disruption, no_location, classifier_failed, duplicate
    outcome: Outcome | None = None
    classification: Classification | None = None
    article_id: str | None = None


def url_hash(url: str) -> bytes:
    return hashlib.sha256(url.strip().encode("utf-8")).digest()


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def store_article(
    conn: psycopg.Connection[Any], article: Article, status: str, classification: Classification | None
) -> str:
    snippet = " ".join(article.text.split())[:300] or None
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO articles (url, url_hash, domain, title, snippet, language, source_country, published_at, fetched_at,
                                     status, text_chars, topics)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s, %s)
               ON CONFLICT (url_hash) DO UPDATE SET status = EXCLUDED.status RETURNING id""",
            (
                article.url,
                url_hash(article.url),
                domain_of(article.url),
                article.title[:500],
                snippet,
                article.lang,
                article.outlet_country,
                article.published_at,
                status,
                len(article.text),
                [classification.event_type] if classification else [],
            ),
        )
        row = cur.fetchone()
    assert row is not None
    return str(row[0])


def store_mentions(conn: psycopg.Connection[Any], article_id: str, located: LocateResult, model_version: str) -> int:
    """Mentions with their candidates, for the location transparency panel."""
    stored = 0
    with conn.cursor() as cur:
        for mention in located.article.mentions:
            if mention.decision is None and not mention.candidates:
                continue
            cur.execute(
                """INSERT INTO mentions (article_id, span_start, span_end, surface, qid, place_id, md_score, el_score, route, decision,
                                         model_version)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (
                    article_id,
                    mention.start,
                    mention.end,
                    mention.surface[:200],
                    mention.decision.qid if mention.decision else None,
                    mention.decision.place_id if mention.decision else None,
                    mention.md_score,
                    mention.el_score,
                    mention.route,
                    f"place:{mention.decision.place_id}" if mention.decision else "unresolved",
                    model_version,
                ),
            )
            mention_id = cur.fetchone()[0]  # type: ignore[index]
            for rank, candidate in enumerate(mention.candidates[:10], start=1):
                cur.execute(
                    """INSERT INTO mention_candidates (mention_id, rank, place_id, bela_score, gazetteer_score, context_score, llm_label)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        mention_id,
                        rank,
                        candidate.place.place_id,
                        candidate.bela_score,
                        candidate.gazetteer_score,
                        candidate.context_score,
                        candidate.llm_label,
                    ),
                )
            stored += 1
    return stored


class NewsIngestor:
    def __init__(
        self,
        conn: psycopg.Connection[Any],
        cfg: EventsConfig,
        pipeline: LinkingPipeline,
        llm: LlmClient,
        ingestor: EventIngestor,
        stages: Stages | None = None,
    ) -> None:
        self.conn, self.cfg, self.pipeline, self.llm, self.ingestor = conn, cfg, pipeline, llm, ingestor
        self.stages = stages or Stages(llm=True)

    def process(self, article: Article) -> NewsResult:
        with self.conn.cursor() as cur:
            cur.execute("SELECT id, status FROM articles WHERE url_hash = %s", (url_hash(article.url),))
            known = cur.fetchone()
        if known is not None:
            return NewsResult("duplicate", article_id=str(known[0]))

        if article.published_at > dt.datetime.now(dt.UTC) + dt.timedelta(days=2):
            return NewsResult("invalid_date")  # a publication date in the future is a feed error; nothing is stored

        label = classify_report(self.llm, article.title, article.text)
        if label is None:
            return NewsResult(
                "classifier_failed", article_id=store_article(self.conn, article, "classifier_failed", None)
            )
        reason = label.drop_reason(self.cfg)
        if reason:
            status = f"dropped_{reason}"
            return NewsResult(status, classification=label, article_id=store_article(self.conn, article, status, label))

        located = locate(
            self.pipeline,
            article.text,
            title=article.title,
            lang=article.lang,
            outlet_country=article.outlet_country,
            stages=self.stages,
        )
        event_location = located.event_location
        article_id = store_article(self.conn, article, "located" if event_location else "no_location", label)
        model_version = f"{self.pipeline.config.version}/{located.article.reranker_version}"
        store_mentions(self.conn, article_id, located, model_version)
        if event_location is None or event_location.confidence < float(
            self.cfg.raw["classification"]["min_location_confidence"]
        ):
            return NewsResult("no_location", classification=label, article_id=article_id)

        ne = NormalizedEvent(
            source_kind="news",
            source_ref=url_hash(article.url).hex()[:32],
            type=label.event_type,
            subtype=label.subtype,
            severity=label.severity,
            title=article.title,
            geometry={"type": "Point", "coordinates": [event_location.lon, event_location.lat]},
            location_level=event_location.level,
            uncertainty_km=event_location.uncertainty_km,
            occurred_at=article.published_at,
            published_at=article.published_at,
            url=article.url,
            snippet=" ".join(article.text.split())[:300],
            location_confidence=event_location.confidence,
            location_place_id=event_location.place.place_id,
            language=article.lang,
            domain=domain_of(article.url),
            article_id=article_id,
            details={"classifier_reason": label.reason, "prompt_version": label.prompt_version},
        )
        outcome = self.ingestor.ingest(ne)
        with self.conn.cursor() as cur:
            cur.execute("UPDATE articles SET status = %s WHERE id = %s", (f"event:{outcome.action}", article_id))
        return NewsResult("event", outcome, label, article_id)
