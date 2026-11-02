"""Load the versioned engine configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@dataclass(frozen=True)
class GeoConfig:
    version: str
    raw: dict[str, Any]

    @property
    def accept_el(self) -> float:
        return float(self.raw["routing"]["accept"]["min_el_score"])

    @property
    def accept_margin(self) -> float:
        return float(self.raw["routing"]["accept"]["min_margin"])

    @property
    def adjudicate_el(self) -> float:
        return float(self.raw["routing"]["adjudicate"]["min_el_score"])

    @property
    def resolve_min_probability(self) -> float:
        return float(self.raw["routing"]["resolve_min_probability"])

    @property
    def override_el(self) -> float:
        return float(self.raw["routing"]["non_geographic_override"]["min_el_score"])

    @property
    def override_advantage(self) -> float:
        return float(self.raw["routing"]["non_geographic_override"]["min_advantage"])

    @property
    def md_threshold(self) -> float:
        return float(self.raw["mention_detection"]["md_threshold"])

    @property
    def max_chars(self) -> int:
        return int(self.raw["chunking"]["max_chars"])

    @property
    def overlap_sentences(self) -> int:
        return int(self.raw["chunking"]["overlap_sentences"])

    @property
    def gazetteer_top_k(self) -> int:
        return int(self.raw["candidates"]["gazetteer_top_k"])

    @property
    def max_candidates(self) -> int:
        return int(self.raw["candidates"]["max_total"])

    @property
    def llm_margin(self) -> float:
        return float(self.raw["llm"]["adjudicate_margin"])

    @property
    def llm_max_candidates(self) -> int:
        return int(self.raw["llm"]["max_candidates"])


def load_config(version: str = "geo_config_v1") -> GeoConfig:
    raw = yaml.safe_load((CONFIG_DIR / f"{version}.yaml").read_text(encoding="utf-8"))
    if raw["version"] != version:
        raise ValueError(f"config file {version}.yaml declares version {raw['version']}")
    return GeoConfig(version, raw)
