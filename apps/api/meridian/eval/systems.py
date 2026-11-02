"""The systems compared in the evaluation, all returning predicted coordinates for gold toponyms.

  S1  largest population GeoNames record matching the string (gold spans given)
  S2  S1 plus country and region context heuristics (gold spans given)
  S4  BELA alone: its nearest entity when that entity is a place
  S5  BELA + type filter + routing + gazetteer fallback + context re-ranking
  S6  S5 + local model adjudication
Systems that detect spans themselves (S4 to S6) are matched to gold spans by overlap.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from meridian.eval.corpora import Document
from meridian.eval.metrics import Gold, error_km, match_spans
from meridian.geo.names import normalize_name
from meridian.linking.context import CountryIndex
from meridian.linking.nel_client import NelMention
from meridian.linking.pipeline import LinkingPipeline, Stages
from meridian.linking.types import MentionResult


@dataclass
class Prediction:
    lat: float
    lon: float
    place_id: int
    route: str | None = None
    confidence: float | None = None


SQL_CANDIDATES = """
SELECT p.id, p.lat, p.lon, p.population, p.country_code, p.admin1_name FROM places p
 WHERE p.source IN ('geonames', 'merged')
   AND (p.name_normalized = %(k)s OR p.id IN (SELECT place_id FROM place_aliases WHERE alias_normalized = %(k)s))
 ORDER BY p.population DESC NULLS LAST, p.id LIMIT 50
"""


class GazetteerBaselines:
    def __init__(self, conn: psycopg.Connection[Any], countries: CountryIndex) -> None:
        self.conn = conn
        self.countries = countries
        self._cache: dict[str, list[tuple[Any, ...]]] = {}

    def candidates(self, surface: str) -> list[tuple[Any, ...]]:
        key = normalize_name(surface)
        if key not in self._cache:
            with self.conn.cursor() as cur:
                cur.execute(SQL_CANDIDATES, {"k": key})
                self._cache[key] = cur.fetchall()
        return self._cache[key]

    def s1(self, gold: Gold) -> Prediction | None:
        rows = self.candidates(gold.surface)
        return Prediction(rows[0][1], rows[0][2], rows[0][0]) if rows else None

    def s2(self, doc: Document, gold: Gold) -> Prediction | None:
        rows = self.candidates(gold.surface)
        if not rows:
            return None
        named = self.countries.countries_in_text(doc.text)
        text_key = normalize_name(doc.text)

        def score(row: tuple[Any, ...]) -> float:
            _, _, _, population, country, admin1 = row
            value = math.log1p(population or 0)
            value += 4.0 if country in named else 0.0
            value += 3.0 if admin1 and normalize_name(admin1) in text_key else 0.0
            return value

        best = max(rows, key=score)
        return Prediction(best[1], best[2], best[0])


def bela_alone(
    pipeline: LinkingPipeline, doc: Document, nel: list[NelMention]
) -> list[tuple[tuple[int, int], Prediction]]:
    known = pipeline_places(pipeline, [m.qid for m in nel if m.qid])
    out = []
    for mention in nel:
        place = known.get(mention.qid or "")
        if place:
            out.append(
                (
                    (mention.start, mention.end),
                    Prediction(place.lat, place.lon, place.place_id, "bela", mention.el_score),
                )
            )
    return out


def pipeline_places(pipeline: LinkingPipeline, qids: list[str]) -> dict[str, Any]:
    from meridian.linking import gazetteer

    return gazetteer.places_by_qid(pipeline.conn, sorted(set(qids)))


def pipeline_spans(results: list[MentionResult]) -> list[tuple[tuple[int, int], MentionResult]]:
    """Every mention the pipeline produced, resolved or not (used to classify misses)."""
    return [((m.start, m.end), m) for m in results]


def classify_miss(gold: Gold, spans: list[tuple[tuple[int, int], MentionResult]]) -> tuple[str, str]:
    """Why a gold toponym has no resolved prediction: the span was never proposed, or it was proposed and not resolved."""
    from meridian.eval.metrics import span_overlap

    best = max(
        ((span_overlap((gold.start, gold.end), span), mention) for span, mention in spans),
        key=lambda x: x[0],
        default=(0.0, None),
    )
    if best[1] is None or best[0] < 0.4:
        return "span_not_detected", ""
    return "span_detected_unresolved", f"{best[1].route}: {best[1].reason}"


def pipeline_predictions(results: list[MentionResult]) -> list[tuple[tuple[int, int], Prediction]]:
    return [
        ((m.start, m.end), Prediction(m.decision.lat, m.decision.lon, m.decision.place_id, m.route, m.confidence))
        for m in results
        if m.decision is not None
    ]


def score_document(
    doc: Document, predictions: list[tuple[tuple[int, int], Prediction]]
) -> tuple[list[float | None], int, int, list[Prediction | None]]:
    """Errors per gold toponym (None when unmatched), predicted count, matched count, and the matched predictions."""
    spans = [(g.start, g.end) for g in doc.gold]
    matched = match_spans(spans, [p[0] for p in predictions])
    errors: list[float | None] = []
    chosen: list[Prediction | None] = []
    for index, gold in enumerate(doc.gold):
        if index in matched:
            prediction = predictions[matched[index]][1]
            errors.append(error_km(gold, prediction.lat, prediction.lon))
            chosen.append(prediction)
        else:
            errors.append(None)
            chosen.append(None)
    return errors, len(predictions), len(matched), chosen


# -- NEL output cache -------------------------------------------------------------------------------------------
def cache_path(root: Path, checkpoint: str) -> Path:
    return root / f"nel_{checkpoint}.jsonl"


def load_nel_cache(path: Path) -> dict[tuple[str, str], list[NelMention]]:
    cache: dict[tuple[str, str], list[NelMention]] = {}
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                cache[(row["corpus"], row["doc_id"])] = [NelMention.from_json(m) for m in row["mentions"]]
    return cache


def append_nel_cache(path: Path, doc: Document, mentions: list[NelMention]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"corpus": doc.corpus, "doc_id": doc.doc_id, "mentions": [m.to_json() for m in mentions]}) + "\n"
        )


STAGES = {
    "S5": Stages(llm=False),
    "S6": Stages(llm=True),
}
