"""BELA joint mention detection and entity linking model (inference only).

A clean reimplementation of the architecture from facebookresearch/BELA (MIT license) that loads
the released checkpoints. The released inference wrapper depends on faiss, fairscale, hydra, and
a pinned protobuf; this version needs only torch and transformers and runs on Apple GPUs (MPS).

Components and checkpoint prefixes:
  encoder             XLM-R large (encoder.transformer.*)
  project_encoder_op  Linear(1024, 300) and LayerNorm(300)
  mention_encoder     Linear(300, 3): start, end, and inside-mention scores per token
  span_encoder        Linear(600, 300) over the first and last token of a span
  el_encoder          MLP over [mention, entity, difference, product, md_score, retrieval score]
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

import torch
from torch import nn
from transformers import AutoConfig, AutoModel

EMBEDDING_DIM = 300
MAX_MENTION_TOKENS = 10  # inclusive span length limit used in training is 10 tokens beyond the start
ENCODER_NAME = "FacebookAI/xlm-roberta-large"
ENCODER_REVISION = "c23d21b0620b635a76227c604d44e43a9f0ee389"  # pinned: downloads are verified against this commit


class ClassificationHead(nn.Module):
    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Linear(4 * dim + 2, dim),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(dim, dim),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(dim, 1),
        )

    def forward(
        self, mention: torch.Tensor, entity: torch.Tensor, md_score: torch.Tensor, retrieval_score: torch.Tensor
    ) -> torch.Tensor:
        features = torch.cat([mention, entity, mention - entity, mention * entity, md_score, retrieval_score], dim=1)
        return self.mlp(features)  # type: ignore[no-any-return]


class SpanEncoder(nn.Module):
    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        super().__init__()
        self.mention_mlp = nn.Linear(dim * 2, dim)

    def forward(self, encodings: torch.Tensor, starts: torch.Tensor, ends: torch.Tensor) -> torch.Tensor:
        """encodings (L, D); starts and ends are token indices (inclusive), shape (M,)."""
        return self.mention_mlp(torch.cat([encodings[starts], encodings[ends]], dim=-1))  # type: ignore[no-any-return]


class MentionHead(nn.Module):
    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        super().__init__()
        self.bound_classifier = nn.Linear(dim, 3)


class HFEncoder(nn.Module):
    def __init__(self, config: Any) -> None:
        super().__init__()
        self.transformer = AutoModel.from_config(config)  # type: ignore[no-untyped-call]


class BelaModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        config = AutoConfig.from_pretrained(ENCODER_NAME, revision=ENCODER_REVISION)
        self.encoder = HFEncoder(config)
        self.project_encoder_op = nn.Sequential(
            nn.Linear(config.hidden_size, EMBEDDING_DIM), nn.LayerNorm(EMBEDDING_DIM)
        )
        self.span_encoder = SpanEncoder()
        self.mention_encoder = MentionHead()
        self.el_encoder = ClassificationHead()

    def encode(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        hidden = self.encoder.transformer(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        return self.project_encoder_op(hidden.float())  # type: ignore[no-any-return]

    def mention_scores(
        self, encodings: torch.Tensor, valid_tokens: int, max_len: int = MAX_MENTION_TOKENS + 1, top_k: int = 50
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Score candidate spans of one passage. encodings is (L, D) with BOS at index 0 and EOS after the pieces."""
        return span_scores(self.mention_encoder.bound_classifier(encodings), valid_tokens, max_len, top_k)


def span_scores(
    logits: torch.Tensor, valid_tokens: int, max_len: int = MAX_MENTION_TOKENS + 1, top_k: int = 50
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Top spans from per-token (start, end, inside) scores of shape (L, 3).

    A span covers pieces start..end inclusive (piece 1 is the first word piece). Its score is
    log p(start) + log p(end) + the sum of the inside scores over the span, as in training. Returns
    (scores, starts, ends) of the best top_k spans of at most max_len pieces.
    """
    start, end, inside = logits[:, 0], logits[:, 1], logits[:, 2]
    cumulative = torch.cumsum(inside, dim=0)
    positions = torch.arange(1, valid_tokens + 1, device=logits.device)
    score_rows, start_rows, end_rows = [], [], []
    for length in range(max_len):
        starts = positions[positions + length <= valid_tokens]
        if starts.numel() == 0:
            break
        ends = starts + length
        score_rows.append(start[starts] + end[ends] + cumulative[ends] - cumulative[starts - 1])
        start_rows.append(starts)
        end_rows.append(ends)
    scores = torch.cat(score_rows)
    starts_all = torch.cat(start_rows)
    ends_all = torch.cat(end_rows)
    top_scores, order = scores.topk(min(top_k, scores.numel()))
    return top_scores, starts_all[order], ends_all[order]


def load_checkpoint(model: BelaModel, path: str | Path) -> dict[str, list[str]]:
    """Load a released checkpoint. weights_only=True means no pickled code is executed."""
    checkpoint = torch.load(str(path), map_location="cpu", mmap=True, weights_only=True)
    state: OrderedDict[str, torch.Tensor] = checkpoint["state_dict"]
    report: dict[str, list[str]] = {"missing": [], "unexpected": []}
    for prefix, module in (
        ("encoder", model.encoder),
        ("project_encoder_op", model.project_encoder_op),
        ("span_encoder", model.span_encoder),
        ("mention_encoder", model.mention_encoder),
        ("el_encoder", model.el_encoder),
    ):
        sub = OrderedDict((k[len(prefix) + 1 :], v) for k, v in state.items() if k.startswith(prefix + "."))
        result = module.load_state_dict(sub, strict=False)
        report["missing"] += [f"{prefix}.{k}" for k in result.missing_keys]
        report["unexpected"] += [f"{prefix}.{k}" for k in result.unexpected_keys]
    return report
