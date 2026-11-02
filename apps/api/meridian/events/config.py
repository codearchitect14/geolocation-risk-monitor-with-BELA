"""Load the versioned event rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
LEVELS = ("low", "medium", "high", "critical")


@dataclass(frozen=True)
class EventsConfig:
    version: str
    raw: dict[str, Any]

    def reliability(self, source_kind: str) -> float:
        return float(self.raw["source_reliability"][source_kind])

    def combined_reliability(self, source_kinds: list[str]) -> float:
        """1 - product(1 - r) over the sources, capped."""
        remaining = 1.0
        for kind in source_kinds:
            remaining *= 1.0 - self.reliability(kind)
        return min(1.0 - remaining, float(self.raw["max_event_reliability"]))

    def level_for(self, score: float) -> str:
        levels = self.raw["exposure"]["levels"]
        if score >= levels["critical"]:
            return "critical"
        if score >= levels["high"]:
            return "high"
        if score >= levels["medium"]:
            return "medium"
        return "low"

    def lambda_km(self, event_type: str, subtype: str | None, magnitude: float | None = None) -> float:
        if subtype == "earthquake" and magnitude is not None:
            chosen = 10.0
            for row in self.raw["exposure"]["earthquake_lambda_km"]:
                if magnitude >= row["min"]:
                    chosen = float(row["lambda"])
            return chosen
        table = self.raw["exposure"]["lambda_km"].get(event_type) or self.raw["exposure"]["lambda_km"]["other"]
        return float(table.get(subtype or "", table["default"]))

    def half_life_hours(self, event_type: str, subtype: str | None) -> float:
        exposure = self.raw["exposure"]
        slow = event_type in exposure["slow_types"] or (subtype or "") in exposure["slow_subtypes"]
        return float(exposure["half_life_hours"]["slow" if slow else "fast"])

    def window_hours(self, event_type: str) -> float:
        clustering = self.raw["clustering"]
        return float(clustering["window_hours"].get(event_type, clustering["default_window_hours"]))

    def quiet_hours(self, event_type: str) -> float:
        status = self.raw["status"]
        return float(status["quiet_hours"].get(event_type, status["default_quiet_hours"]))


def load_events_config(version: str = "events_config_v1") -> EventsConfig:
    raw = yaml.safe_load((CONFIG_DIR / f"{version}.yaml").read_text(encoding="utf-8"))
    if raw["version"] != version:
        raise ValueError(f"config file {version}.yaml declares version {raw['version']}")
    return EventsConfig(version, raw)
