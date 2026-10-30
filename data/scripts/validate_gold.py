"""Validate the gold evaluation sets and report progress against their quotas.

python validate_gold.py                       validate data/gold/*.jsonl
python validate_gold.py --agreement a.jsonl b.jsonl
                                             agreement between two annotators
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import common

MENTION_LABELS = {"PLACE", "FACILITY", "NOT_A_PLACE"}
EVENT_TYPES = {
    "industrial_accident",
    "natural_hazard",
    "transport_disruption",
    "labor_action",
    "civil_unrest",
    "security_incident",
    "infrastructure_outage",
    "health_outbreak",
    "other",
    "none",
}
LOCATION_LEVELS = {"facility", "city", "admin2", "admin1", "country", "unknown"}
TARGET_PATTERN = re.compile(r"^(Q\d+|gn:\d+|NIL)$")
SPLITS = {"dev", "test"}
QUOTAS = {
    "mention_sentences": 400,
    "ambiguous_mentions": 100,
    "facility_mentions": 50,
    "non_english_sentences": 60,
    "event_articles": 300,
}


def validate_mention(row: dict[str, Any]) -> list[str]:
    errors = []
    text = row.get("text")
    if not isinstance(text, str) or not text:
        return ["text missing"]
    if row.get("split") not in SPLITS:
        errors.append("split must be dev or test")
    if not row.get("lang"):
        errors.append("lang missing")
    for i, m in enumerate(row.get("mentions", [])):
        where = f"mention {i}"
        start, end = m.get("start"), m.get("end")
        if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text)):
            errors.append(f"{where}: invalid span")
            continue
        if text[start:end] != m.get("surface"):
            errors.append(f"{where}: surface does not match text[start:end]")
        if m.get("label") not in MENTION_LABELS:
            errors.append(f"{where}: invalid label")
        target = m.get("target")
        if not isinstance(target, str) or not TARGET_PATTERN.match(target):
            errors.append(f"{where}: invalid target")
        if m.get("label") == "NOT_A_PLACE" and target != "NIL":
            errors.append(f"{where}: NOT_A_PLACE must have target NIL")
    return errors


def validate_event(row: dict[str, Any]) -> list[str]:
    errors = []
    if not row.get("title"):
        errors.append("title missing")
    if not str(row.get("url", "")).startswith(("http://", "https://")):
        errors.append("url invalid")
    if len(row.get("snippet") or "") > 300:
        errors.append("snippet longer than 300 characters")
    if row.get("split") not in SPLITS:
        errors.append("split must be dev or test")
    if row.get("event_type") not in EVENT_TYPES:
        errors.append("invalid event_type")
    if row.get("event_type") not in (None, "none") and row.get("severity") not in (1, 2, 3, 4):
        errors.append("severity must be 1 to 4")
    if row.get("private_person_subject"):
        if row.get("location"):
            errors.append("private person subject must not carry a location")
        return errors
    location = row.get("location")
    if row.get("event_type") not in (None, "none") and location is not None:
        if location.get("level") not in LOCATION_LEVELS:
            errors.append("invalid location level")
        lat, lon = location.get("lat"), location.get("lon")
        if lat is not None and lon is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
            errors.append("location coordinates out of range")
    return errors


def progress(mentions: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, int]:
    all_mentions = [m for row in mentions for m in row.get("mentions", [])]
    return {
        "mention_sentences": len(mentions),
        "ambiguous_mentions": sum(1 for m in all_mentions if m.get("ambiguous")),
        "facility_mentions": sum(1 for m in all_mentions if m.get("label") == "FACILITY"),
        "non_english_sentences": sum(1 for r in mentions if r.get("lang") != "en"),
        "event_articles": len(events),
    }


def load(path: Path) -> list[dict[str, Any]]:
    return list(common.iter_jsonl(path)) if path.exists() else []


def cohen_kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    if n == 0:
        return float("nan")
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in ca.keys() | cb.keys()) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def agreement(path_a: Path, path_b: Path) -> dict[str, float]:
    """Agreement between two annotators on items present in both files."""
    result: dict[str, float] = {}
    ev_a = {r["id"]: r for r in load(path_a) if "event_type" in r}
    ev_b = {r["id"]: r for r in load(path_b) if "event_type" in r}
    shared = sorted(ev_a.keys() & ev_b.keys())
    if shared:
        result["event_items"] = float(len(shared))
        result["event_type_kappa"] = cohen_kappa(
            [ev_a[i]["event_type"] for i in shared], [ev_b[i]["event_type"] for i in shared]
        )
        result["event_level_agreement"] = sum(
            (ev_a[i].get("location") or {}).get("level") == (ev_b[i].get("location") or {}).get("level") for i in shared
        ) / len(shared)
    mn_a = {r["id"]: r for r in load(path_a) if "mentions" in r}
    mn_b = {r["id"]: r for r in load(path_b) if "mentions" in r}
    shared = sorted(mn_a.keys() & mn_b.keys())
    if shared:
        span_a = {(i, m["start"], m["end"]): m["target"] for i in shared for m in mn_a[i]["mentions"]}
        span_b = {(i, m["start"], m["end"]): m["target"] for i in shared for m in mn_b[i]["mentions"]}
        both = span_a.keys() & span_b.keys()
        union = span_a.keys() | span_b.keys()
        result["mention_items"] = float(len(shared))
        result["span_agreement"] = len(both) / len(union) if union else float("nan")
        result["target_agreement"] = sum(span_a[k] == span_b[k] for k in both) / len(both) if both else float("nan")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold-dir", type=Path, default=common.DEFAULT_DATA_DIR / "gold")
    parser.add_argument("--agreement", nargs=2, type=Path, metavar=("A", "B"))
    args = parser.parse_args(argv)

    if args.agreement:
        for key, value in agreement(*args.agreement).items():
            print(f"{key:24} {value:.3f}")
        return 0

    mentions = load(args.gold_dir / "mentions.jsonl")
    events = load(args.gold_dir / "events.jsonl")
    errors = 0
    for name, rows, check in (("mentions", mentions, validate_mention), ("events", events, validate_event)):
        seen: set[str] = set()
        for row in rows:
            row_id = str(row.get("id"))
            problems = check(row) + ([f"duplicate id {row_id}"] if row_id in seen else [])
            seen.add(row_id)
            for problem in problems:
                print(f"{name}[{row_id}]: {problem}", file=sys.stderr)
                errors += 1
    counts = progress(mentions, events)
    for key, quota in QUOTAS.items():
        print(f"{key:24} {counts[key]:>5} / {quota}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
