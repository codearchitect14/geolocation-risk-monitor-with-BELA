"""Geoparsing metrics: distance error, accuracy within a radius, error-curve area, and span matching."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from meridian.linking.context import haversine_km

MAX_ERROR_KM = 20039.0  # half the Earth's circumference: the worst possible error


@dataclass(frozen=True)
class Gold:
    doc_id: str
    corpus: str
    start: int
    end: int
    surface: str
    lat: float
    lon: float
    place_id: int | None  # the knowledge-base place for the gold identifier, when it exists


def span_overlap(a: tuple[int, int], b: tuple[int, int]) -> float:
    """Intersection over union of two character spans."""
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union else 0.0


def match_spans(gold: list[tuple[int, int]], predicted: list[tuple[int, int]], min_iou: float = 0.4) -> dict[int, int]:
    """Greedy one-to-one matching of gold spans to predicted spans by overlap. Returns gold index to predicted index."""
    pairs = sorted(
        ((span_overlap(g, p), gi, pi) for gi, g in enumerate(gold) for pi, p in enumerate(predicted)), reverse=True
    )
    matched: dict[int, int] = {}
    used: set[int] = set()
    for score, gi, pi in pairs:
        if score < min_iou:
            break
        if gi not in matched and pi not in used:
            matched[gi] = pi
            used.add(pi)
    return matched


def error_km(gold: Gold, lat: float, lon: float) -> float:
    return haversine_km(gold.lat, gold.lon, lat, lon)


def curve_auc(errors: list[float]) -> float:
    """Area under the cumulative error curve on a log distance axis, normalized to 0..1 (lower is better)."""
    if not errors:
        return float("nan")
    scale = math.log1p(MAX_ERROR_KM)
    return sum(math.log1p(min(e, MAX_ERROR_KM)) for e in errors) / (len(errors) * scale)


def summarize(errors: list[float | None], total_gold: int, predicted_resolved: int, matched: int) -> dict[str, float]:
    """errors has one entry per gold toponym: a distance in km, or None when no prediction was matched."""
    present = [e for e in errors if e is not None]
    all_errors = [e if e is not None else MAX_ERROR_KM for e in errors]
    precision = matched / predicted_resolved if predicted_resolved else 0.0
    recall = matched / total_gold if total_gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "gold": float(total_gold),
        "detected": float(matched),
        "detection_precision": round(precision, 4),
        "detection_recall": round(recall, 4),
        "detection_f1": round(f1, 4),
        "acc_25km": round(sum(1 for e in all_errors if e <= 25) / max(total_gold, 1), 4),
        "acc_161km": round(sum(1 for e in all_errors if e <= 161) / max(total_gold, 1), 4),
        "acc_25km_matched": round(sum(1 for e in present if e <= 25) / max(len(present), 1), 4),
        "acc_161km_matched": round(sum(1 for e in present if e <= 161) / max(len(present), 1), 4),
        "median_error_km": round(statistics.median(present), 1) if present else float("nan"),
        "mean_error_km": round(statistics.fmean(present), 1) if present else float("nan"),
        "auc_matched": round(curve_auc(present), 4),
        "auc_all": round(curve_auc(all_errors), 4),
    }
