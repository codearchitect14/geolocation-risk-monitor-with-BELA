"""Confidence calibration with isotonic regression, stored as plain JSON arrays (no pickle)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression


@dataclass
class Calibrator:
    x: list[float]
    y: list[float]

    @classmethod
    def fit(cls, scores: list[float], correct: list[bool]) -> Calibrator:
        model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        model.fit(np.array(scores), np.array(correct, dtype=float))
        return cls([float(v) for v in model.X_thresholds_], [float(v) for v in model.y_thresholds_])

    def __call__(self, score: float) -> float:
        return float(np.interp(score, self.x, self.y))


def reliability_table(scores: list[float], correct: list[bool], bins: int = 10) -> list[dict[str, float]]:
    """Mean predicted confidence versus observed accuracy per equal-width bin."""
    rows = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        members = [(s, c) for s, c in zip(scores, correct, strict=True) if lo <= s < hi or (i == bins - 1 and s == 1.0)]
        if members:
            rows.append(
                {
                    "bin_low": lo,
                    "bin_high": hi,
                    "n": float(len(members)),
                    "mean_confidence": round(sum(s for s, _ in members) / len(members), 4),
                    "accuracy": round(sum(c for _, c in members) / len(members), 4),
                }
            )
    return rows


def expected_calibration_error(scores: list[float], correct: list[bool], bins: int = 10) -> float:
    table = reliability_table(scores, correct, bins)
    total = sum(r["n"] for r in table)
    return (
        round(sum(r["n"] * abs(r["mean_confidence"] - r["accuracy"]) for r in table) / total, 4)
        if total
        else float("nan")
    )


def save(calibrators: dict[str, Calibrator], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({k: {"x": c.x, "y": c.y} for k, c in calibrators.items()}, indent=1) + "\n", encoding="utf-8"
    )


def load(path: Path) -> dict[str, Calibrator]:
    if not path.exists():
        return {}
    return {k: Calibrator(v["x"], v["y"]) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
