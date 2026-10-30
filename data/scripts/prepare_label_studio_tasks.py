"""Build Label Studio task files from harvested news metadata.

Mention tasks oversample ambiguous place names, facility words, and non-English
titles so the gold set reaches its quotas. Event tasks use harvested titles and
snippets (at most 300 characters) with a link to the original article. Output is
written to data/annotation/tasks/.

Load the labeling configurations from data/annotation/label_studio/ into two
Label Studio projects, then import the generated JSON files.
"""

from __future__ import annotations

import argparse
import html
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

import common

AMBIGUOUS_NAMES = [
    "Springfield",
    "Paris",
    "Georgetown",
    "Santiago",
    "Valencia",
    "Birmingham",
    "Alexandria",
    "Victoria",
    "Washington",
    "Portland",
    "San Jose",
    "London",
    "Cambridge",
    "Richmond",
    "Salem",
    "Columbia",
    "Rochester",
    "Manchester",
    "Lima",
    "Granada",
]
FACILITY_WORDS = [
    "port",
    "airport",
    "terminal",
    "refinery",
    "plant",
    "factory",
    "power station",
    "dam",
    "bridge",
    "tunnel",
    "railway station",
    "border crossing",
    "base",
    "hospital",
    "stadium",
    "puerto",
    "aeropuerto",
    "refinería",
    "hafen",
    "flughafen",
    "aéroport",
    "porto",
    "aeroporto",
]
SEED = 42


def load_titles(directories: list[Path]) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for directory in directories:
        for path in sorted(directory.glob("*.jsonl")):
            for record in common.iter_jsonl(path):
                title = (record.get("title") or "").strip()
                url = record.get("url")
                if title and url and len(title) > 25:
                    records.setdefault(url, record)
    return list(records.values())


def pattern_for(words: list[str]) -> re.Pattern[str]:
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)


def mention_tasks(records: list[dict[str, Any]], count: int, rng: random.Random) -> list[dict[str, Any]]:
    ambiguous = pattern_for(AMBIGUOUS_NAMES)
    facility = pattern_for(FACILITY_WORDS)
    pools = {"ambiguous": [], "facility": [], "non_english": [], "other": []}  # type: dict[str, list[dict[str, Any]]]
    for record in records:
        language = (record.get("language") or "").lower()
        title = record["title"]
        if ambiguous.search(title):
            pools["ambiguous"].append(record)
        elif facility.search(title):
            pools["facility"].append(record)
        elif language and language != "english":
            pools["non_english"].append(record)
        else:
            pools["other"].append(record)
    quotas = {"ambiguous": 0.30, "facility": 0.20, "non_english": 0.25, "other": 0.25}
    chosen: list[tuple[str, dict[str, Any]]] = []
    for name, share in quotas.items():
        pool = pools[name]
        rng.shuffle(pool)
        chosen += [(name, r) for r in pool[: int(count * share)]]
    rng.shuffle(chosen)
    return [
        {"data": {"text": r["title"], "lang": r.get("language"), "url": r["url"], "pool": name}}
        for name, r in chosen[:count]
    ]


def event_tasks(
    records: list[dict[str, Any]], count: int, rng: random.Random, snippets: dict[str, str]
) -> list[dict[str, Any]]:
    sample = rng.sample(records, min(count, len(records)))  # noqa: S311
    tasks = []
    for r in sample:
        url = r["url"]
        link = f'<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">Open original article</a>'
        tasks.append(
            {
                "data": {
                    "title": r["title"],
                    "snippet": snippets.get(url, ""),
                    "url": url,
                    "lang": r.get("language"),
                    "link_html": link,
                }
            }
        )
    return tasks


def load_snippets(directory: Path) -> dict[str, str]:
    snippets: dict[str, str] = {}
    if directory.exists():
        for path in directory.glob("*.jsonl"):
            for record in common.iter_jsonl(path):
                if record.get("snippet"):
                    snippets[record["url"]] = record["snippet"][:300]
    return snippets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mentions", type=int, default=600, help="mention tasks to generate")
    parser.add_argument("--events", type=int, default=450, help="event tasks to generate")
    parser.add_argument("--out", type=Path, default=common.DEFAULT_DATA_DIR / "annotation" / "tasks")
    args = parser.parse_args(argv)

    records = load_titles([common.raw_dir("news", "gdelt")])
    if not records:
        print("No harvested titles found. Run the GDELT harvester first.", file=sys.stderr)
        return 1
    rng = random.Random(SEED)  # noqa: S311
    snippets = load_snippets(common.raw_dir("news", "articles"))
    args.out.mkdir(parents=True, exist_ok=True)
    outputs = {
        "mention_tasks.json": mention_tasks(records, args.mentions, rng),
        "event_tasks.json": event_tasks(records, args.events, rng, snippets),
    }
    for name, tasks in outputs.items():
        (args.out / name).write_text(json.dumps(tasks, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{name}: {len(tasks)} tasks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
