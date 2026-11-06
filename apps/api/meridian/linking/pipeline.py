"""Place linking pipeline: BELA mentions, type filter, routing, gazetteer fallback, context re-ranking,
and optional local-model adjudication.

Stages (each can be switched off for the ablations in the evaluation harness):
  1. split the article into passages and link them (done by the caller or by link_article)
  2. type filter: keep candidates that are places; discard confident non-geographic links
  3. routing: accept / adjudicate / fallback by score and margin (geo_config)
  4. fallback spans: capitalized strings that match a gazetteer name but were missed by BELA
  5. context re-ranking of candidates for adjudicate and fallback mentions
  6. local-model adjudication when the two best candidates remain close
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import httpx
import psycopg
from rapidfuzz import fuzz

from meridian.geo.names import normalize_name
from meridian.linking import gazetteer
from meridian.linking.chunk import make_chunks
from meridian.linking.config import GeoConfig, load_config
from meridian.linking.context import ArticleContext, CountryIndex
from meridian.linking.features import pair_features
from meridian.linking.nel_client import NelClient, NelMention
from meridian.linking.reranker import Reranker
from meridian.linking.spans import capitalized_spans
from meridian.linking.types import MentionResult, PlaceRecord, Route, ScoredCandidate
from meridian.llm.client import LlmClient, LlmError
from meridian.llm.prompts import ADJUDICATE_VERSION, adjudicate_prompt
from meridian.llm.schemas import PlaceChoice

log = logging.getLogger("meridian.linking")

LLM_CONCURRENCY = 4


@dataclass
class Stages:
    type_filter: bool = True
    routing: bool = True
    gazetteer_fallback: bool = True
    rerank: bool = True
    llm: bool = True
    degrade: bool = False  # production news path: continue with the gazetteer when the entity linker is unreachable
    force_rerank: bool = False  # training only: re-rank every mention to collect features, ignoring routing


@dataclass
class ArticleResult:
    mentions: list[MentionResult]
    config_version: str
    reranker_version: str
    llm_prompt_version: str | None
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def resolved(self) -> list[MentionResult]:
        return [m for m in self.mentions if m.decision is not None]


def sentence_around(text: str, start: int, end: int, radius: int = 220) -> str:
    left = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    right_candidates = [i for i in (text.find(". ", end), text.find("\n", end)) if i != -1]
    right = min(right_candidates) if right_candidates else len(text)
    begin = max(left + 1 if left != -1 else 0, start - radius)
    return text[begin : min(right + 1, end + radius)].strip()


class LinkingPipeline:
    def __init__(
        self,
        conn: psycopg.Connection[Any],
        nel: NelClient | None = None,
        config: GeoConfig | None = None,
        reranker: Reranker | None = None,
        llm: LlmClient | None = None,
        countries: CountryIndex | None = None,
    ) -> None:
        self.conn = conn
        self.nel = nel
        self.config = config or load_config()
        self.reranker = reranker or Reranker(None, "rules_v1")
        self.llm = llm
        self.countries = countries or CountryIndex.load(conn)

    # -- stage 1 -----------------------------------------------------------------------------------------------
    def run_nel(self, text: str, lang: str | None = None) -> list[NelMention]:
        """Chunk the article, link every chunk, and merge mentions by absolute span (best score wins)."""
        if self.nel is None:
            raise RuntimeError("no NEL client configured")
        chunks = make_chunks(text, lang or "en", self.config.max_chars, self.config.overlap_sentences)
        linked = self.nel.link([(str(i), c.text) for i, c in enumerate(chunks)])
        merged: dict[tuple[int, int], NelMention] = {}
        for index, chunk in enumerate(chunks):
            for mention in linked.get(str(index), []):
                shifted = NelMention(
                    mention.start + chunk.start,
                    mention.end + chunk.start,
                    mention.surface,
                    mention.qid,
                    mention.md_score,
                    mention.el_score,
                    mention.candidates,
                    mention.place_candidates,
                )
                key = (shifted.start, shifted.end)
                if key not in merged or shifted.md_score > merged[key].md_score:
                    merged[key] = shifted
        return sorted(merged.values(), key=lambda m: m.start)

    # -- stages 2 to 6 -------------------------------------------------------------------------------------------
    def resolve(
        self,
        text: str,
        nel_mentions: list[NelMention],
        *,
        lang: str | None = None,
        outlet_country: str | None = None,
        stages: Stages | None = None,
    ) -> ArticleResult:
        stages = stages or Stages()
        cfg = self.config
        context = ArticleContext(
            text=text, lang=lang, outlet_country=outlet_country, named_countries=self.countries.countries_in_text(text)
        )
        qids = sorted({q for m in nel_mentions for q, _ in m.place_candidates + m.candidates})
        known = gazetteer.places_by_qid(self.conn, qids)

        results: list[MentionResult] = []
        pending: list[tuple[MentionResult, list[tuple[PlaceRecord, float, int]]]] = []
        for mention in nel_mentions:
            place_cands = [(known[q], s, rank) for rank, (q, s) in enumerate(mention.place_candidates) if q in known]
            place_cands.sort(key=lambda c: -c[1])
            best_el = place_cands[0][1] if place_cands else 0.0
            second_el = place_cands[1][1] if len(place_cands) > 1 else 0.0
            margin = best_el - second_el
            overall = max(mention.candidates, key=lambda c: c[1], default=(None, 0.0))
            non_geo = (
                stages.type_filter
                and overall[0] is not None
                and overall[0] not in known
                and overall[1] >= cfg.override_el
                and overall[1] - best_el >= cfg.override_advantage
            )

            result = MentionResult(
                start=mention.start,
                end=mention.end,
                surface=mention.surface,
                source="bela",
                md_score=mention.md_score,
                el_score=best_el,
                margin=margin,
                route="unresolved",
                decision=None,
            )
            if not place_cands:
                result.route, result.reason = "fallback", "no place candidate from the entity linker"
            elif non_geo and overall[1] >= cfg.accept_el:
                result.route, result.reason = "unresolved", f"non-geographic entity {overall[0]} outscores places"
                results.append(result)
                continue
            elif non_geo:
                result.route, result.reason = "fallback", f"possible non-geographic entity {overall[0]}"
            elif stages.force_rerank:
                result.route, result.reason = "adjudicate", "feature collection"
            elif not stages.routing or (best_el >= cfg.accept_el and margin >= cfg.accept_margin):
                result.route = "accept"
                result.decision = place_cands[0][0]
                result.confidence = best_el
                context.resolved.append(result.decision)
            elif best_el >= cfg.adjudicate_el:
                result.route, result.reason = "adjudicate", "score or margin below the accept thresholds"
            else:
                result.route, result.reason = "fallback", "entity linking score below the adjudication threshold"
            result.candidates = [ScoredCandidate(p, bela_score=s) for p, s, _ in place_cands]
            result.origin_route = result.route
            results.append(result)
            if result.route in ("adjudicate", "fallback"):
                pending.append((result, place_cands))

        # First re-rank what BELA proposed. Mentions that still do not resolve free their span for the fallback.
        for result, place_cands in pending:
            if result.decision is None:
                self._rerank(result, place_cands, context, stages)
        context.resolved = [r.decision for r in results if r.decision is not None]
        if stages.gazetteer_fallback:
            pending += self._fallback_spans(text, results)
        for _round in range(1):  # one pass over everything, now that the confident places are known
            for result, place_cands in pending:
                if result.route != "accept":
                    self._rerank(result, place_cands, context, stages)
            context.resolved = [r.decision for r in results if r.decision is not None]

        llm_failures = 0
        if stages.llm and self.llm is not None:
            llm_failures = self._adjudicate_all([r for r, _ in pending], text, context)
            context.resolved = [r.decision for r in results if r.decision is not None]

        results.sort(key=lambda r: r.start)
        counts: dict[str, int] = {}
        for r in results:
            counts[r.route] = counts.get(r.route, 0) + 1
        return ArticleResult(
            results,
            cfg.version,
            self.reranker.version,
            ADJUDICATE_VERSION if (stages.llm and self.llm) else None,
            {"routes": counts, "mentions": len(results), "llm_failures": llm_failures},
        )

    def _fallback_spans(
        self, text: str, existing: list[MentionResult]
    ) -> list[tuple[MentionResult, list[tuple[PlaceRecord, float, int]]]]:
        # A resolved place occupies its span. Mentions that did not resolve (an organization such as "Mansfield Police
        # Department", a discarded non-place link) do not, so the place name inside them can still be found.
        discarded = [m for m in existing if m.decision is None and m.reason.startswith("non-geographic")]
        # A discarded link blocks its span only when the whole string is itself a place name ("Washington said");
        # a longer organization name ("Dayton Police Department") lets the place inside be found.
        blocking = gazetteer.has_exact_name(self.conn, [m.surface for m in discarded])
        occupied = [
            (m.start, m.end) for m in existing if m.decision is not None or (m in discarded and m.surface in blocking)
        ]
        spans = [s for s in capitalized_spans(text) if all(s.end <= a or s.start >= b for a, b in occupied)]
        matches = gazetteer.has_exact_name(self.conn, [s.text for s in spans])
        out: list[tuple[MentionResult, list[tuple[PlaceRecord, float, int]]]] = []
        taken: list[tuple[int, int]] = []
        for span in sorted((s for s in spans if s.text in matches), key=lambda s: (-(s.end - s.start), s.start)):
            if any(not (span.end <= a or span.start >= b) for a, b in taken):
                continue
            taken.append((span.start, span.end))
            result = MentionResult(
                start=span.start,
                end=span.end,
                surface=span.text,
                source="gazetteer",
                md_score=0.0,
                el_score=0.0,
                margin=0.0,
                route="fallback",
                decision=None,
                reason="capitalized string matching a gazetteer name",
            )
            existing.append(result)
            result.origin_route = "fallback"
            out.append((result, []))
        return out

    def _rerank(
        self,
        result: MentionResult,
        place_cands: list[tuple[PlaceRecord, float, int]],
        context: ArticleContext,
        stages: Stages,
    ) -> None:
        bela = {p.place_id: (s, rank) for p, s, rank in place_cands}
        by_id: dict[int, tuple[PlaceRecord, float, bool]] = {p.place_id: (p, 0.0, False) for p, _, _ in place_cands}
        for place, similarity in gazetteer.gazetteer_candidates(
            self.conn, result.surface, k=self.config.gazetteer_top_k
        ):
            by_id.setdefault(place.place_id, (place, similarity, True))
            if place.place_id in by_id and by_id[place.place_id][1] < similarity:
                by_id[place.place_id] = (place, similarity, True)
        normalized = normalize_name(result.surface)
        scored: list[ScoredCandidate] = []
        feature_rows: list[dict[str, float]] = []
        for place, similarity, _from_gazetteer in list(by_id.values())[: self.config.max_candidates]:
            if similarity == 0.0:
                similarity = fuzz.ratio(normalized, normalize_name(place.name)) / 100.0
            bela_score, rank = bela.get(place.place_id, (0.0, None))
            features = pair_features(
                result.surface,
                result.start,
                result.end,
                place,
                context=context,
                countries=self.countries,
                bela_score=bela_score,
                bela_rank=rank,
                name_similarity=similarity,
                matched_primary=normalize_name(place.name) == normalized,
            )
            scored.append(ScoredCandidate(place, bela_score=bela_score, gazetteer_score=similarity, features=features))
            feature_rows.append(features)
        if not scored:
            result.route, result.reason = "unresolved", "no candidates"
            return
        probabilities = self.reranker.score(feature_rows) if stages.rerank else [c.gazetteer_score for c in scored]
        for candidate, probability in zip(scored, probabilities, strict=True):
            candidate.context_score = probability
        scored.sort(key=lambda c: -(c.context_score or 0.0))
        result.candidates = scored
        best = scored[0]
        second = scored[1].context_score or 0.0 if len(scored) > 1 else 0.0
        result.margin = (best.context_score or 0.0) - second
        if (best.context_score or 0.0) >= self.config.resolve_min_probability:
            result.decision = best.place
            result.confidence = best.context_score or 0.0
        else:
            result.decision = None
            result.route, result.reason = "unresolved", "best candidate below the resolution threshold"

    def _llm_prompt(self, result: MentionResult, text: str, context: ArticleContext) -> str | None:
        """The adjudication prompt for a mention, or None when the model should not be asked."""
        if self.llm is None or len(result.candidates) < 2 or result.route == "accept":
            return None
        if result.margin >= self.config.llm_margin and result.decision is not None:
            return None
        # The model arbitrates between plausible candidates. A capitalized string whose best candidate is poor
        # (and that BELA did not propose for adjudication) is left unresolved without a model call.
        best_score = result.candidates[0].context_score or 0.0
        if result.origin_route != "adjudicate" and best_score < self.config.resolve_min_probability:
            return None
        top = result.candidates[: self.config.llm_max_candidates]
        hints = []
        if context.named_countries:
            hints.append("countries named in the article: " + ", ".join(sorted(context.named_countries)))
        if context.outlet_country:
            hints.append(f"outlet country: {context.outlet_country}")
        return adjudicate_prompt(
            sentence_around(text, result.start, result.end),
            result.surface,
            [c.place.label for c in top],
            "; ".join(hints) or "none",
        )

    def _adjudicate_all(self, results: list[MentionResult], text: str, context: ArticleContext) -> int:
        """Ask the local model about every mention that needs it, a few requests at a time. Returns how many requests failed."""
        assert self.llm is not None
        jobs = [(r, prompt) for r in results if (prompt := self._llm_prompt(r, text, context)) is not None]
        if not jobs:
            return 0

        def ask(prompt: str) -> PlaceChoice | None:
            try:
                completion = self.llm.complete(prompt, PlaceChoice, max_tokens=self.config_llm_tokens())  # type: ignore[union-attr]
            except LlmError as exc:
                log.warning("llm adjudication failed: %s", exc)
                return None
            choice: PlaceChoice = completion.parsed  # type: ignore[assignment]
            return choice

        with ThreadPoolExecutor(max_workers=LLM_CONCURRENCY) as pool:
            choices = list(pool.map(ask, [prompt for _, prompt in jobs]))
        for (result, _), choice in zip(jobs, choices, strict=True):
            if choice is not None:
                self._apply_choice(result, choice)
        return sum(choice is None for choice in choices)

    def _apply_choice(self, result: MentionResult, choice: PlaceChoice) -> None:
        top = result.candidates[: self.config.llm_max_candidates]
        for index, candidate in enumerate(top):
            candidate.llm_label = "chosen" if index == choice.choice else "rejected"
        if choice.choice is not None and 0 <= choice.choice < len(top):
            result.decision = top[choice.choice].place
            result.confidence = max(result.confidence, choice.confidence * 0.9)
            result.route = "adjudicate"
            result.reason = f"local model: {choice.reason}"
        elif choice.choice is None:
            result.decision, result.route = None, "unresolved"
            result.reason = f"local model: {choice.reason}"

    def config_llm_tokens(self) -> int:
        return int(self.config.raw["llm"]["max_tokens"])

    def link_article(
        self, text: str, *, lang: str | None = None, outlet_country: str | None = None, stages: Stages | None = None
    ) -> ArticleResult:
        stages = stages or Stages()
        degraded: list[str] = []
        try:
            mentions = self.run_nel(text, lang)
        except (httpx.HTTPError, RuntimeError) as exc:
            if not stages.degrade:
                raise
            log.warning("entity linker unavailable, using gazetteer rules only: %s", exc)
            mentions, degraded = [], ["nel"]
        result = self.resolve(text, mentions, lang=lang, outlet_country=outlet_country, stages=stages)
        if result.stats.get("llm_failures"):
            degraded.append("llm")
        result.stats["degraded"] = degraded
        return result


_ = Route  # re-exported for type hints in callers
