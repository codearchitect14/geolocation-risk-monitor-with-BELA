from __future__ import annotations

from pydantic import BaseModel, Field


class PassageIn(BaseModel):
    id: str
    text: str = Field(max_length=20_000)
    lang: str | None = None


class LinkRequest(BaseModel):
    passages: list[PassageIn] = Field(max_length=64)
    top_k: int = Field(default=10, ge=1, le=20)


class CandidateOut(BaseModel):
    qid: str
    score: float
    similarity: float


class MentionOut(BaseModel):
    start: int
    end: int
    surface: str
    qid: str | None
    md_score: float
    el_score: float
    candidates: list[CandidateOut]
    place_candidates: list[CandidateOut]


class PassageOut(BaseModel):
    id: str
    mentions: list[MentionOut]


class LinkResponse(BaseModel):
    model: str
    results: list[PassageOut]
    seconds: float


class EmbedRequest(BaseModel):
    texts: list[str] = Field(max_length=256)


class EmbedResponse(BaseModel):
    model: str
    dimensions: int
    embeddings: list[list[float]]
