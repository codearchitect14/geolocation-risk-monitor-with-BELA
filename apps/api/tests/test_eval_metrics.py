import math

from meridian.eval.corpora import split_of
from meridian.eval.metrics import MAX_ERROR_KM, curve_auc, match_spans, span_overlap, summarize


def test_span_overlap_and_matching() -> None:
    assert span_overlap((0, 10), (0, 10)) == 1.0
    assert span_overlap((0, 6), (0, 12)) == 0.5
    assert span_overlap((0, 5), (6, 9)) == 0.0
    gold = [(0, 6), (20, 30)]
    predicted = [(0, 12), (21, 30), (40, 45)]
    assert match_spans(gold, predicted) == {0: 0, 1: 1}
    assert match_spans([(0, 5)], [(10, 15)]) == {}


def test_matching_is_one_to_one() -> None:
    assert len(match_spans([(0, 5), (0, 5)], [(0, 5)])) == 1


def test_summarize_counts_misses_as_wrong() -> None:
    result = summarize([5.0, 100.0, None, 3000.0], total_gold=4, predicted_resolved=4, matched=3)
    assert result["acc_25km"] == 0.25 and result["acc_161km"] == 0.5
    assert result["acc_25km_matched"] == round(1 / 3, 4)
    assert result["median_error_km"] == 100.0
    assert result["detection_recall"] == 0.75 and result["detection_precision"] == 0.75


def test_auc_bounds() -> None:
    assert curve_auc([0.0, 0.0]) == 0.0
    assert math.isclose(curve_auc([MAX_ERROR_KM]), 1.0)
    assert curve_auc([10.0]) < curve_auc([1000.0])


def test_split_is_stable_and_roughly_balanced() -> None:
    assert split_of("lgl", "42") == split_of("lgl", "42")
    shares = sum(split_of("lgl", str(i)) == "dev" for i in range(2000)) / 2000
    assert 0.45 < shares < 0.55
