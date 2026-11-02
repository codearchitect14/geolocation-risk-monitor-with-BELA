"""Data structures shared by the linking pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Route = Literal["accept", "adjudicate", "fallback", "unresolved"]


@dataclass
class PlaceRecord:
    place_id: int
    name: str
    type: str
    country_code: str | None
    admin1_name: str | None
    population: int | None
    lat: float
    lon: float
    uncertainty_km: float | None
    qid: str | None = None
    geonames_id: int | None = None
    location_level: str | None = None
    country_level: bool = False

    @property
    def label(self) -> str:
        """Short description used in prompts and the transparency panel."""
        region = f", {self.admin1_name}" if self.admin1_name and self.admin1_name != self.name else ""
        country = f", {self.country_code}" if self.country_code else ""
        return f"{self.name}{region}{country} ({self.type.replace('_', ' ')})"


@dataclass
class ScoredCandidate:
    place: PlaceRecord
    bela_score: float = 0.0
    gazetteer_score: float = 0.0
    context_score: float | None = None
    llm_label: str | None = None
    features: dict[str, float] = field(default_factory=dict)


@dataclass
class MentionResult:
    start: int
    end: int
    surface: str
    source: Literal["bela", "gazetteer"]
    md_score: float
    el_score: float
    margin: float
    route: Route
    decision: PlaceRecord | None
    candidates: list[ScoredCandidate] = field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0
    origin_route: Route = "fallback"  # the route chosen by the router, before re-ranking and adjudication
