"""Routing, type filter, fallback, and re-ranking on a small hand-built place table."""

from __future__ import annotations

from typing import Any

import httpx
import psycopg
import pytest

from meridian.geo.names import normalize_name
from meridian.linking.context import CountryIndex
from meridian.linking.nel_client import NelMention
from meridian.linking.pipeline import LinkingPipeline, Stages
from meridian.linking.reranker import Reranker
from meridian.llm.client import LlmClient

PLACES = [
    # id, qid, name, type, country, admin1, population, lat, lon
    (1, "Q1", "Springfield", "city", "US", "Illinois", 116250, 39.80, -89.64),
    (2, "Q2", "Springfield", "city", "US", "Missouri", 167882, 37.22, -93.30),
    (3, "Q3", "Dayton", "city", "US", "Ohio", 137644, 39.76, -84.19),
    (4, "Q4", "Ohio", "admin1", "US", "Ohio", 11_800_000, 40.37, -82.99),
    (5, "Q5", "Illinois", "admin1", "US", "Illinois", 12_800_000, 40.0, -89.0),
    (6, "Q6", "United States", "country", "US", None, 330_000_000, 39.8, -98.6),
    (7, "Q7", "Washington", "admin1", "US", "Washington", 7_700_000, 47.4, -121.5),
    (8, "Q8", "Rotterdam", "city", "NL", "South Holland", 650_000, 51.92, 4.48),
    (9, "Q9", "Netherlands", "country", "NL", None, 17_000_000, 52.1, 5.3),
]


@pytest.fixture
def pipeline(conn: psycopg.Connection[Any]) -> LinkingPipeline:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE places, ref_country_info CASCADE")
        cur.execute(
            "INSERT INTO ref_country_info (iso2, iso3, name) VALUES ('US', 'USA', 'United States'), ('NL', 'NLD', 'Netherlands')"
        )
        for pid, qid, name, ptype, cc, admin1, pop, lat, lon in PLACES:
            cur.execute(
                """INSERT INTO places (id, qid, name, name_normalized, type, country_code, admin1_name, population, lat, lon,
                                       centroid, geom, source, uncertainty_km, location_level)
                   OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                                                   ST_SetSRID(ST_MakePoint(%s, %s), 4326), 'wikidata', 25, 'city')""",
                (pid, qid, name, normalize_name(name), ptype, cc, admin1, pop, lat, lon, lon, lat, lon, lat),
            )
    conn.commit()
    return LinkingPipeline(conn, None, reranker=Reranker(None, "rules_v1"))


def mention(
    text: str,
    surface: str,
    places: list[tuple[str, float]],
    overall: list[tuple[str, float]] | None = None,
    md: float = 0.9,
) -> NelMention:
    start = text.index(surface)
    best = places[0] if places else (None, 0.0)
    return NelMention(start, start + len(surface), surface, best[0], md, best[1], overall or places, places)


def test_confident_link_is_accepted(pipeline: LinkingPipeline) -> None:
    text = "A fire broke out in Dayton on Tuesday."
    result = pipeline.resolve(text, [mention(text, "Dayton", [("Q3", 0.95), ("Q8", 0.20)])])
    only = result.mentions[0]
    assert only.route == "accept" and only.decision is not None and only.decision.name == "Dayton"
    assert result.config_version == "geo_config_v1"


def test_ambiguous_namesake_is_decided_by_the_qualifier(pipeline: LinkingPipeline) -> None:
    text = "Police in Springfield, Illinois said the explosion injured two workers."
    result = pipeline.resolve(
        text, [mention(text, "Springfield", [("Q2", 0.55), ("Q1", 0.50)])], stages=Stages(llm=False)
    )
    only = result.mentions[0]
    assert only.route == "adjudicate"
    assert only.decision is not None and only.decision.qid == "Q1"
    assert only.candidates[0].context_score is not None and only.candidates[0].features["qualifier_match"] == 1.0


def test_country_in_the_article_decides_when_bela_is_unsure(pipeline: LinkingPipeline) -> None:
    text = "Rotterdam is the largest port in the Netherlands."
    nl = mention(text, "Netherlands", [("Q9", 0.97)])
    city = mention(text, "Rotterdam", [("Q8", 0.45), ("Q3", 0.40)])
    result = pipeline.resolve(text, [city, nl], stages=Stages(llm=False))
    assert next(m for m in result.mentions if m.surface == "Rotterdam").decision.qid == "Q8"  # type: ignore[union-attr]


def test_confident_non_place_link_is_discarded(pipeline: LinkingPipeline) -> None:
    text = "Washington said the plan would proceed."
    nel = mention(text, "Washington", [("Q7", 0.30)], overall=[("Q_PERSON", 0.92), ("Q7", 0.30)])
    result = pipeline.resolve(text, [nel])
    only = result.mentions[0]
    assert only.route == "unresolved" and only.decision is None and "non-geographic" in only.reason


def test_type_filter_can_be_switched_off(pipeline: LinkingPipeline) -> None:
    text = "Washington said the plan would proceed."
    nel = mention(text, "Washington", [("Q7", 0.30)], overall=[("Q_PERSON", 0.92), ("Q7", 0.30)])
    result = pipeline.resolve(text, [nel], stages=Stages(type_filter=False, llm=False, gazetteer_fallback=False))
    assert result.mentions[0].route != "unresolved" or result.mentions[0].decision is None


def test_fallback_finds_capitalized_gazetteer_names_bela_missed(pipeline: LinkingPipeline) -> None:
    text = "The blaze in Dayton, Ohio spread quickly."
    result = pipeline.resolve(text, [mention(text, "Dayton", [("Q3", 0.9)])])
    surfaces = {m.surface: m for m in result.mentions}
    assert "Ohio" in surfaces and surfaces["Ohio"].source == "gazetteer"
    assert surfaces["Ohio"].decision is not None and surfaces["Ohio"].decision.name == "Ohio"
    assert (
        pipeline.resolve(text, [mention(text, "Dayton", [("Q3", 0.9)])], stages=Stages(gazetteer_fallback=False)).stats[
            "mentions"
        ]
        == 1
    )


def test_unknown_names_stay_unresolved(pipeline: LinkingPipeline) -> None:
    text = "The blaze in Zzyzx Falls spread quickly."
    nel = mention(text, "Zzyzx Falls", [])
    result = pipeline.resolve(text, [nel])
    assert result.mentions[0].decision is None and result.mentions[0].route in ("fallback", "unresolved")


def test_countries_in_text(pipeline: LinkingPipeline) -> None:
    index = CountryIndex.load(pipeline.conn)
    assert index.countries_in_text("Officials in the Netherlands and United States said") == {"NL", "US"}


def test_language_model_adjudication_uses_the_model_choice(pipeline: LinkingPipeline) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = '{"reason": "Missouri police", "choice": 0, "confidence": 0.9}'
        return httpx.Response(
            200, json={"choices": [{"message": {"content": body}}], "usage": {"completion_tokens": 10}}
        )

    llm = LlmClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    pipeline.llm = llm
    text = "The Springfield plant closed after the explosion."
    nel = mention(text, "Springfield", [("Q1", 0.52), ("Q2", 0.50)])
    result = pipeline.resolve(text, [nel])
    only = result.mentions[0]
    assert only.reason.startswith("local model") and only.decision is not None
    assert only.candidates[0].llm_label == "chosen" and result.llm_prompt_version == "adjudicate_v1"


def test_language_model_is_not_asked_about_implausible_candidates(pipeline: LinkingPipeline) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        body = '{"reason": "x", "choice": 0, "confidence": 0.9}'
        return httpx.Response(
            200, json={"choices": [{"message": {"content": body}}], "usage": {"completion_tokens": 5}}
        )

    pipeline.llm = LlmClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    # "Washington" appears only as a capitalized string; with nothing supporting any candidate the model stays out of it.
    text = "Reporters asked about it on Monday, Washington."
    pipeline.resolve(text, [])
    plausible = "The Springfield plant closed after the explosion."
    pipeline.resolve(plausible, [mention(plausible, "Springfield", [("Q1", 0.52), ("Q2", 0.50)])])
    assert len(calls) == 1  # only the BELA mention proposed for adjudication reached the model


def test_place_name_inside_an_organization_mention_is_still_found(pipeline: LinkingPipeline) -> None:
    text = "The Dayton Police Department closed the road."
    nel = mention(text, "Dayton Police Department", [("Q3", 0.12)], overall=[("Q_ORG", 0.9), ("Q3", 0.12)])
    result = pipeline.resolve(text, [nel], stages=Stages(llm=False))
    found = [m for m in result.mentions if m.decision is not None]
    assert [m.surface for m in found] == ["Dayton"] and found[0].decision is not None and found[0].decision.qid == "Q3"
    assert found[0].source == "gazetteer"


def test_all_caps_dateline_is_found(pipeline: LinkingPipeline) -> None:
    text = "DAYTON -- Crews responded on Tuesday."
    result = pipeline.resolve(text, [], stages=Stages(llm=False))
    assert any(m.surface == "DAYTON" and m.decision is not None for m in result.mentions)
