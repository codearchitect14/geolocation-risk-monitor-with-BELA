"""Context re-ranker: a small gradient boosting model with a hand-set rules fallback."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits

from meridian.linking.features import FEATURE_NAMES, to_vector

# Hand-set weights used before a model is trained, so the pipeline always works.
RULE_WEIGHTS = {
    "bela_score": 1.6,
    "bela_rank_inverse": 0.4,
    "name_exact": 0.8,
    "name_primary": 0.2,
    "name_similarity": 0.8,
    "log_population": 0.12,
    "type_settlement": 0.3,
    "type_admin": 0.2,
    "country_named_in_article": 1.0,
    "outlet_country_match": 0.5,
    "qualifier_match": 1.6,
    "same_country_share": 0.9,
    "same_admin1_share": 0.5,
    "facility_word_agrees": 0.3,
    "article_language_alias": 0.1,
}


def rule_score(features: dict[str, float]) -> float:
    total = sum(RULE_WEIGHTS.get(name, 0.0) * value for name, value in features.items())
    if features.get("has_cluster"):
        total -= 0.12 * features["log_distance_to_cluster"]
    return float(1 / (1 + np.exp(-(total - 3.0))))


@dataclass
class Reranker:
    model: HistGradientBoostingClassifier | None
    version: str

    def score(self, rows: list[dict[str, float]]) -> list[float]:
        if not rows:
            return []
        if self.model is None:
            return [rule_score(r) for r in rows]
        matrix = np.array([to_vector(r) for r in rows], dtype=np.float64)
        # Scoring a handful of candidates is far faster on one thread than with the default thread pool.
        with threadpool_limits(limits=1):
            return [float(p) for p in self.model.predict_proba(matrix)[:, 1]]

    @classmethod
    def load(cls, path: Path | None) -> Reranker:
        if path is None or not path.exists():
            return cls(None, "rules_v1")
        payload = joblib.load(path)
        if payload["features"] != FEATURE_NAMES:
            raise ValueError("re-ranker was trained with a different feature set")
        return cls(payload["model"], payload["version"])

    @staticmethod
    def train(
        rows: list[dict[str, float]], labels: list[int], version: str, out: Path, seed: int = 42
    ) -> dict[str, Any]:
        matrix = np.array([to_vector(r) for r in rows], dtype=np.float64)
        model = HistGradientBoostingClassifier(
            max_depth=5,
            learning_rate=0.08,
            max_iter=250,
            l2_regularization=1.0,
            random_state=seed,
            early_stopping=True,
            validation_fraction=0.15,
        )
        model.fit(matrix, np.array(labels))
        out.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": model, "features": FEATURE_NAMES, "version": version}, out)
        out.with_suffix(".json").write_text(
            json.dumps(
                {"version": version, "features": FEATURE_NAMES, "rows": len(rows), "positives": int(sum(labels))},
                indent=1,
            )
        )
        return {"rows": len(rows), "positives": int(sum(labels)), "iterations": int(model.n_iter_)}
