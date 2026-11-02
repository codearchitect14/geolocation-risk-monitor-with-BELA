"""Mention detection and linking for batches of passages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import torch

from nel_service.index import EntityIndex
from nel_service.model import BelaModel, load_checkpoint
from nel_service.tokenizer import PAD_ID, Encoded, Tokenizer

MD_THRESHOLD = 0.2
TOP_K = 10


@dataclass
class Candidate:
    qid: str
    score: float  # entity linking probability from the BELA classification head
    similarity: float  # inner product with the mention representation


@dataclass
class Mention:
    start: int
    end: int
    surface: str
    md_score: float
    qid: str | None
    el_score: float
    candidates: list[Candidate] = field(default_factory=list)
    place_candidates: list[Candidate] = field(default_factory=list)


@dataclass
class Passage:
    id: str
    text: str
    lang: str | None = None


def resolve_overlaps(spans: list[tuple[float, int, int]]) -> list[tuple[float, int, int]]:
    """Keep the highest scoring span of every overlapping group (ties go to the longer span)."""
    kept: list[tuple[float, int, int]] = []
    for score, start, end in sorted(spans, key=lambda s: (-s[0], -(s[2] - s[1]))):
        if all(end < other_start or start > other_end for _, other_start, other_end in kept):
            kept.append((score, start, end))
    return sorted(kept, key=lambda s: s[1])


class Linker:
    def __init__(
        self,
        checkpoint: Path,
        sentencepiece_model: Path,
        index: EntityIndex,
        device: torch.device,
        md_threshold: float = MD_THRESHOLD,
        dtype: torch.dtype = torch.float16,
    ) -> None:
        self.device = device
        self.index = index
        self.md_threshold = md_threshold
        self.tokenizer = Tokenizer(sentencepiece_model)
        self.model = BelaModel()
        self.load_report = load_checkpoint(self.model, checkpoint)
        self.model.encoder.to(device=device, dtype=dtype)
        for part in (
            self.model.project_encoder_op,
            self.model.span_encoder,
            self.model.mention_encoder,
            self.model.el_encoder,
        ):
            part.to(device=device, dtype=torch.float32)
        self.model.eval()
        self.checkpoint_name = checkpoint.name

    @torch.inference_mode()
    def link(self, passages: list[Passage], top_k: int = TOP_K) -> list[list[Mention]]:
        encoded = [self.tokenizer.encode(p.text) for p in passages]
        longest = max(len(e.token_ids) for e in encoded)
        ids = torch.full((len(passages), longest), PAD_ID, dtype=torch.long)
        mask = torch.zeros((len(passages), longest), dtype=torch.long)
        for row, e in enumerate(encoded):
            ids[row, : len(e.token_ids)] = torch.tensor(e.token_ids)
            mask[row, : len(e.token_ids)] = 1
        encodings = self.model.encode(ids.to(self.device), mask.to(self.device))

        spans: list[list[tuple[float, int, int]]] = []
        owners: list[tuple[int, tuple[float, int, int]]] = []
        for row, e in enumerate(encoded):
            valid = len(e.token_ids) - 2
            top_scores, starts, ends = self.model.mention_scores(encodings[row], valid)
            probabilities = torch.sigmoid(top_scores)
            keep = probabilities > self.md_threshold
            proposals = [
                (float(p), int(s), int(t))
                for p, s, t in zip(
                    probabilities[keep].tolist(), starts[keep].tolist(), ends[keep].tolist(), strict=True
                )
            ]
            chosen = resolve_overlaps(proposals)
            spans.append(chosen)
            for item in chosen:
                owners.append((row, item))
        if not owners:
            return [[] for _ in passages]

        rows_idx = torch.tensor([o[0] for o in owners], device=self.device)
        start_idx = torch.tensor([o[1][1] for o in owners], device=self.device)
        end_idx = torch.tensor([o[1][2] for o in owners], device=self.device)
        md = torch.tensor([o[1][0] for o in owners], device=self.device).unsqueeze(1)
        mention_repr = self._span_reprs(encodings, rows_idx, start_idx, end_idx)

        queries = mention_repr.to(torch.float16)
        full_scores, full_rows = self.index.full.search(queries, top_k)
        place_scores, place_local = self.index.places.search(queries, top_k)
        place_rows = self.index.place_row_to_global(place_local)

        full_el = self._el_scores(mention_repr, md, full_scores, self.index.full.gather(full_rows))
        place_el = self._el_scores(mention_repr, md, place_scores, self.index.places.gather(place_local))

        result: list[list[Mention]] = [[] for _ in passages]
        full_rows_cpu, place_rows_cpu = full_rows.cpu().tolist(), place_rows.cpu().tolist()
        for m, (row, (md_score, st, en)) in enumerate(owners):
            enc: Encoded = encoded[row]
            text = passages[row].text
            start, end = self.tokenizer.char_span(enc, st, en, text)
            candidates = sorted(
                (
                    Candidate(self.index.qid(r), float(el), float(sim))
                    for r, el, sim in zip(full_rows_cpu[m], full_el[m].tolist(), full_scores[m].tolist(), strict=True)
                ),
                key=lambda c: -c.score,
            )
            place_candidates = sorted(
                (
                    Candidate(self.index.qid(r), float(el), float(sim))
                    for r, el, sim in zip(
                        place_rows_cpu[m], place_el[m].tolist(), place_scores[m].tolist(), strict=True
                    )
                ),
                key=lambda c: -c.score,
            )
            top = max(candidates, key=lambda c: c.similarity)  # BELA links the nearest entity
            result[row].append(
                Mention(
                    start=start,
                    end=end,
                    surface=text[start:end],
                    md_score=md_score,
                    qid=top.qid,
                    el_score=next(c.score for c in candidates if c.qid == top.qid),
                    candidates=candidates,
                    place_candidates=place_candidates,
                )
            )
        return result

    def _span_reprs(
        self, encodings: torch.Tensor, rows: torch.Tensor, starts: torch.Tensor, ends: torch.Tensor
    ) -> torch.Tensor:
        first = encodings[rows, starts]
        last = encodings[rows, ends]
        return self.model.span_encoder.mention_mlp(torch.cat([first, last], dim=-1))  # type: ignore[no-any-return]

    def _el_scores(
        self, mention_repr: torch.Tensor, md: torch.Tensor, similarities: torch.Tensor, entity_vectors: torch.Tensor
    ) -> torch.Tensor:
        m, k, _ = entity_vectors.shape
        mention = mention_repr.unsqueeze(1).expand(m, k, -1).reshape(m * k, -1)
        entities = entity_vectors.float().reshape(m * k, -1)
        md_flat = md.unsqueeze(1).expand(m, k, 1).reshape(m * k, 1)
        sims = similarities.reshape(m * k, 1)
        logits = self.model.el_encoder(mention, entities, md_flat, sims)
        return torch.sigmoid(logits).reshape(m, k)
