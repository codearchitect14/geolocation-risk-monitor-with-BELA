"""Classifier smoke check on author-written headlines.

This is NOT a gold evaluation: the headlines were written by the project team to exercise each event type, a few
languages, and the private-person rule, and were not sampled from real traffic. It detects regressions in prompt or model
changes. It does not estimate real-world accuracy.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from meridian.config import REPO_ROOT
from meridian.events.classify import classify_report
from meridian.llm.client import LlmClient

SMOKE_PATH = REPO_ROOT / "data" / "seed" / "event_classifier_smoke.jsonl"


def run(path: Path = SMOKE_PATH) -> dict[str, object]:
    llm = LlmClient()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    type_ok = sev_ok = sev_near = private_ok = failed = 0
    confusion: Counter[tuple[str, str]] = Counter()
    misses: list[dict[str, object]] = []
    for row in rows:
        label = classify_report(llm, row["title"])
        if label is None:
            failed += 1
            continue
        got_type = "none" if label.private_person else label.event_type
        expected_type = "none" if row["expected_private_person"] else row["expected_type"]
        type_ok += got_type == expected_type
        private_ok += label.private_person == row["expected_private_person"]
        if row["expected_type"] != "none" and not row["expected_private_person"]:
            sev_ok += label.severity == row["expected_severity"]
            sev_near += abs(label.severity - row["expected_severity"]) <= 1
        if got_type != expected_type:
            confusion[(expected_type, got_type)] += 1
            misses.append({"title": row["title"], "expected": expected_type, "got": got_type})
    scored_sev = sum(1 for r in rows if r["expected_type"] != "none" and not r["expected_private_person"])
    return {
        "note": "author-written smoke set, not a gold evaluation",
        "n": len(rows),
        "classifier_failures": failed,
        "type_accuracy": round(type_ok / len(rows), 3),
        "private_person_accuracy": round(private_ok / len(rows), 3),
        "severity_exact": round(sev_ok / scored_sev, 3),
        "severity_within_one": round(sev_near / scored_sev, 3),
        "misses": misses,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", type=Path, default=SMOKE_PATH)
    args = parser.parse_args()
    print(json.dumps(run(args.path), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
