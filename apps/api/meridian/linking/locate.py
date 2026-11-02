"""Link an article and select its event location in one call (the engine behind POST /locate)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from meridian.linking.calibration import Calibrator
from meridian.linking.event_location import EventLocation, select_event_location
from meridian.linking.pipeline import ArticleResult, LinkingPipeline, Stages
from meridian.linking.types import MentionResult, PlaceRecord

DISCLAIMER = (
    "Signals are situational awareness derived from public news and public data feeds. They are not official warnings. "
    "Verify with local authorities and follow their guidance."
)


@dataclass
class LocateResult:
    article: ArticleResult
    event_location: EventLocation | None
    text: str


def locate(
    pipeline: LinkingPipeline,
    text: str,
    *,
    title: str = "",
    lang: str | None = None,
    outlet_country: str | None = None,
    stages: Stages | None = None,
) -> LocateResult:
    full = f"{title}\n\n{text}" if title else text
    article = pipeline.link_article(full, lang=lang, outlet_country=outlet_country, stages=stages)
    lead_chars = 400
    event = select_event_location(
        pipeline.conn,
        article.mentions,
        full,
        title_chars=len(title),
        lead_chars=lead_chars,
        outlet_country=outlet_country,
    )
    return LocateResult(article, event, full)


def place_json(place: PlaceRecord) -> dict[str, Any]:
    return {
        "place_id": place.place_id,
        "qid": place.qid,
        "geonames_id": place.geonames_id,
        "name": place.name,
        "type": place.type,
        "country_code": place.country_code,
        "admin1": place.admin1_name,
        "lat": place.lat,
        "lon": place.lon,
        "uncertainty_km": place.uncertainty_km,
        "location_level": place.location_level,
        "country_level": place.country_level,
    }


def mention_json(mention: MentionResult, calibrators: dict[str, Calibrator] | None = None) -> dict[str, Any]:
    calibrated = None
    if calibrators and mention.route in calibrators and mention.decision is not None:
        calibrated = round(calibrators[mention.route](mention.confidence), 4)
    return {
        "start": mention.start,
        "end": mention.end,
        "surface": mention.surface,
        "source": mention.source,
        "route": mention.route,
        "reason": mention.reason,
        "md_score": round(mention.md_score, 4),
        "el_score": round(mention.el_score, 4),
        "margin": round(mention.margin, 4),
        "confidence": round(mention.confidence, 4),
        "calibrated_confidence": calibrated,
        "place": place_json(mention.decision) if mention.decision else None,
        "candidates": [
            {
                "place": place_json(c.place),
                "bela_score": round(c.bela_score, 4),
                "gazetteer_score": round(c.gazetteer_score, 4),
                "context_score": None if c.context_score is None else round(c.context_score, 4),
                "llm_label": c.llm_label,
            }
            for c in mention.candidates[:10]
        ],
    }


def event_json(event: EventLocation | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "place": place_json(event.place),
        "lat": event.lat,
        "lon": event.lon,
        "uncertainty_km": event.uncertainty_km,
        "level": event.level,
        "country_level": event.country_level,
        "confidence": event.confidence,
        "widened": event.widened,
        "alertable_against_sites": not event.country_level,
    }


def result_json(result: LocateResult, calibrators: dict[str, Calibrator] | None = None) -> dict[str, Any]:
    return {
        "config_version": result.article.config_version,
        "reranker_version": result.article.reranker_version,
        "llm_prompt_version": result.article.llm_prompt_version,
        "stats": result.article.stats,
        "mentions": [mention_json(m, calibrators) for m in result.article.mentions],
        "event_location": event_json(result.event_location),
        "disclaimer": DISCLAIMER,
    }


def connect_for_service() -> psycopg.Connection[Any]:
    from meridian.db import connect

    return connect(autocommit=True)
