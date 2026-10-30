"""Convert a Label Studio JSON export into gold JSONL records.

  python export_label_studio.py mentions export.json data/gold/mentions.jsonl --split dev
  python export_label_studio.py events export.json data/gold/events.jsonl --split test

Only tasks with a submitted, non-cancelled annotation are exported. Annotator
identity is not written to the output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def first_annotation(task: dict[str, Any]) -> list[dict[str, Any]] | None:
    for annotation in task.get("annotations", []):
        if not annotation.get("was_cancelled"):
            return list(annotation.get("result", []))
    return None


def convert_mention_task(task: dict[str, Any], prefix: str, split: str) -> dict[str, Any] | None:
    result = first_annotation(task)
    if result is None:
        return None
    text = task["data"]["text"]
    regions: dict[str, dict[str, Any]] = {}
    for item in result:
        rid = str(item.get("id"))
        value = item.get("value", {})
        if item["type"] == "labels":
            regions[rid] = {
                "start": value["start"],
                "end": value["end"],
                "surface": value["text"],
                "label": value["labels"][0],
                "target": "NIL",
                "ambiguous": False,
            }
    for item in result:
        rid = str(item.get("id"))
        if rid not in regions:
            continue
        value = item.get("value", {})
        if item["type"] == "textarea" and value.get("text"):
            regions[rid]["target"] = str(value["text"][0]).strip()
        elif item["type"] == "choices" and item.get("from_name") == "ambiguity":
            regions[rid]["ambiguous"] = value["choices"][0] == "ambiguous"
    return {
        "id": f"{prefix}{task['id']:05d}",
        "text": text,
        "lang": task["data"].get("lang") or "en",
        "split": split,
        "mentions": sorted(regions.values(), key=lambda m: m["start"]),
    }


def convert_event_task(task: dict[str, Any], prefix: str, split: str) -> dict[str, Any] | None:
    result = first_annotation(task)
    if result is None:
        return None
    choices: dict[str, str] = {}
    texts: dict[str, str] = {}
    for item in result:
        value = item.get("value", {})
        if item["type"] == "choices":
            choices[item["from_name"]] = value["choices"][0] if value.get("choices") else ""
            if item["from_name"] == "private_person":
                choices["private_person"] = "yes"
        elif item["type"] == "textarea" and value.get("text"):
            texts[item["from_name"]] = str(value["text"][0]).strip()
    data = task["data"]
    event_type = choices.get("event_type", "none")
    severity = int(choices["severity"]) if choices.get("severity") else None
    private = choices.get("private_person") == "yes"
    location = None
    if not private and texts.get("event_location"):
        location = {
            "name": texts["event_location"],
            "target": "NIL",
            "lat": None,
            "lon": None,
            "level": choices.get("location_level", "unknown"),
        }
    return {
        "id": f"{prefix}{task['id']:05d}",
        "url": data["url"],
        "title": data["title"],
        "snippet": (data.get("snippet") or "")[:300],
        "lang": data.get("lang") or "en",
        "split": split,
        "event_type": event_type,
        "severity": severity,
        "location": location,
        "assets": [],
        "private_person_subject": private,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("kind", choices=["mentions", "events"])
    parser.add_argument("export", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    args = parser.parse_args(argv)

    tasks = json.loads(args.export.read_text(encoding="utf-8"))
    convert, prefix = (convert_mention_task, "m") if args.kind == "mentions" else (convert_event_task, "e")
    rows = [r for t in tasks if (r := convert(t, prefix, args.split))]
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"wrote {len(rows)} records to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
