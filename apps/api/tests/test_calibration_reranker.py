import random
from pathlib import Path

from meridian.linking import calibration
from meridian.linking.features import FEATURE_NAMES
from meridian.linking.reranker import Reranker, rule_score


def row(**overrides: float) -> dict[str, float]:
    base = dict.fromkeys(FEATURE_NAMES, 0.0)
    base.update(overrides)
    return base


def test_isotonic_calibration_repairs_overconfidence() -> None:
    rng = random.Random(1)
    scores = [rng.random() for _ in range(2000)]
    correct = [rng.random() < s * 0.6 for s in scores]  # the model claims s but is right 60% as often
    calibrator = calibration.Calibrator.fit(scores, correct)
    before = calibration.expected_calibration_error(scores, correct)
    after = calibration.expected_calibration_error([calibrator(s) for s in scores], correct)
    assert after < before and after < 0.05
    assert calibrator(0.9) <= 1.0 and calibrator(0.1) >= 0.0
    assert calibrator(0.2) <= calibrator(0.8)  # monotone


def test_reliability_table_bins() -> None:
    table = calibration.reliability_table([0.05, 0.15, 0.95, 1.0], [False, False, True, True], bins=10)
    assert [r["n"] for r in table] == [1.0, 1.0, 2.0]
    assert table[-1]["accuracy"] == 1.0


def test_calibrators_roundtrip_as_json(tmp_path: Path) -> None:
    calibrator = calibration.Calibrator.fit([0.1, 0.4, 0.6, 0.9] * 20, [False, False, True, True] * 20)
    path = tmp_path / "cal.json"
    calibration.save({"accept": calibrator}, path)
    loaded = calibration.load(path)
    assert loaded["accept"](0.5) == calibrator(0.5)
    assert calibration.load(tmp_path / "missing.json") == {}


def test_rules_prefer_qualifier_country_and_population() -> None:
    strong = row(
        name_exact=1,
        name_primary=1,
        name_similarity=1,
        qualifier_match=1,
        country_named_in_article=1,
        log_population=12,
    )
    weak = row(name_exact=1, name_primary=1, name_similarity=1, log_population=6)
    assert rule_score(strong) > rule_score(weak) > 0.0
    assert Reranker(None, "rules_v1").score([strong, weak])[0] > 0.5


def test_trained_reranker_learns_and_roundtrips(tmp_path: Path) -> None:
    rng = random.Random(3)
    rows, labels = [], []
    for _ in range(600):
        good = rng.random() < 0.5
        rows.append(
            row(
                qualifier_match=1.0 if good else 0.0,
                log_population=rng.uniform(5, 14),
                name_similarity=rng.uniform(0.6, 1),
            )
        )
        labels.append(1 if good else 0)
    path = tmp_path / "rerank.joblib"
    report = Reranker.train(rows, labels, "test_v1", path)
    assert report["positives"] == sum(labels)
    loaded = Reranker.load(path)
    assert loaded.version == "test_v1"
    high, low = loaded.score(
        [row(qualifier_match=1.0, log_population=9, name_similarity=0.9), row(log_population=9, name_similarity=0.9)]
    )
    assert high > 0.8 > 0.2 > low


def test_missing_model_falls_back_to_rules(tmp_path: Path) -> None:
    assert Reranker.load(tmp_path / "none.joblib").version == "rules_v1"
