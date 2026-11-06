"""HTTP client for the NEL service."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_URL = "http://127.0.0.1:8082"


@dataclass
class NelMention:
    start: int
    end: int
    surface: str
    qid: str | None
    md_score: float
    el_score: float
    candidates: list[tuple[str, float]] = field(default_factory=list)  # overall top candidates (qid, el score)
    place_candidates: list[tuple[str, float]] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict[str, Any], offset: int = 0) -> NelMention:
        return cls(
            start=data["start"] + offset,
            end=data["end"] + offset,
            surface=data["surface"],
            qid=data["qid"],
            md_score=data["md_score"],
            el_score=data["el_score"],
            candidates=[(c["qid"], c["score"]) for c in data["candidates"]],
            place_candidates=[(c["qid"], c["score"]) for c in data["place_candidates"]],
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "surface": self.surface,
            "qid": self.qid,
            "md_score": self.md_score,
            "el_score": self.el_score,
            "candidates": [{"qid": q, "score": s, "similarity": 0.0} for q, s in self.candidates],
            "place_candidates": [{"qid": q, "score": s, "similarity": 0.0} for q, s in self.place_candidates],
        }


class NelClient:
    def __init__(self, base_url: str | None = None, timeout: float = 300.0, client: httpx.Client | None = None) -> None:
        self.base_url = (base_url or os.environ.get("NEL_URL") or DEFAULT_URL).rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)

    def healthy(self) -> bool:
        try:
            return bool(self._client.get(f"{self.base_url}/health", timeout=3).status_code == 200)
        except httpx.HTTPError:
            return False

    def link(self, passages: list[tuple[str, str]], top_k: int = 10, batch: int = 32) -> dict[str, list[NelMention]]:
        """Link passages (id, text). Returns mentions per passage id with offsets relative to the passage."""
        results: dict[str, list[NelMention]] = {}
        for offset in range(0, len(passages), batch):
            part = passages[offset : offset + batch]
            body = {"passages": [{"id": pid, "text": text} for pid, text in part], "top_k": top_k}
            for attempt in range(4):
                try:
                    response = self._client.post(f"{self.base_url}/v1/link", json=body)
                except httpx.TransportError:  # timeouts and refused connections: back off, then give up
                    if attempt == 3:
                        raise
                    time.sleep(min(4.0, 0.5 * 2**attempt))
                    continue
                if response.status_code == 503 and attempt < 3:
                    time.sleep(float(response.headers.get("Retry-After", "2")))
                    continue
                response.raise_for_status()
                break
            for item in response.json()["results"]:
                results[item["id"]] = [NelMention.from_json(m) for m in item["mentions"]]
        return results

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.post(f"{self.base_url}/v1/embed", json={"texts": texts})
        response.raise_for_status()
        return response.json()["embeddings"]  # type: ignore[no-any-return]
