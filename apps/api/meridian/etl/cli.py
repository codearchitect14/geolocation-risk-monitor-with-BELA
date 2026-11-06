"""Command line entry point: python -m meridian.etl <command>."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

from meridian.config import REPO_ROOT, get_settings
from meridian.db import connect, etl_step
from meridian.etl import (
    embeddings,
    finalize,
    geonames,
    hierarchy,
    merge,
    quality,
    query_plans,
    reference,
    search_eval,
    wikidata,
    wikidata_api,
)

BUILD_STEPS = ["reference", "stage-geonames", "stage-wikidata", "merge", "hierarchy", "finalize"]


def write_reports(conn: Any, quality_result: dict[str, Any], eval_result: dict[str, Any] | None) -> None:
    out = get_settings().data_dir / "processed"
    out.mkdir(parents=True, exist_ok=True)
    payload = {"quality": quality_result, "search_eval": eval_result}
    (out / "place_kb_report.json").write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m meridian.etl")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (*BUILD_STEPS, "build", "quality", "eval", "plans"):
        sub.add_parser(name)
    stage_g = sub.choices["stage-geonames"]
    stage_g.add_argument("--min-population", type=int, default=1000)
    stage_g.add_argument("--include-minor-facilities", action="store_true")
    build = sub.choices["build"]
    build.add_argument("--min-population", type=int, default=1000)
    build.add_argument("--force", action="store_true", help="rebuild even if dependent tables hold data")
    build.add_argument(
        "--demo",
        action="store_true",
        help="small knowledge base for the demo: GeoNames cities of 15,000 people or more, no aliases, no Wikidata subset",
    )
    sub.choices["merge"].add_argument("--force", action="store_true")
    enrich = sub.add_parser("enrich", help="add missing Wikidata places for the QIDs BELA proposes")
    enrich.add_argument("--nel-cache", required=True, help="JSONL cache written by meridian.eval cache-nel")
    enrich.add_argument("--top", type=int, default=3, help="candidates per mention to consider")
    enrich.add_argument("--min-score", type=float, default=0.05)
    enrich.add_argument("--limit", type=int, help="fetch at most this many QIDs")
    embed = sub.add_parser("embed")
    embed.add_argument("--kinds", default="name,description,alias")
    embed.add_argument("--limit", type=int)
    embed.add_argument("--device")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    with connect() as conn:
        command = args.command
        if command in ("reference", "build"):
            reference.run(conn)
        if command in ("stage-geonames", "build"):
            demo = bool(getattr(args, "demo", False))
            geonames.run(
                conn,
                min_population=15000 if demo else args.min_population,
                include_minor_facilities=getattr(args, "include_minor_facilities", False),
                **({"places_file": "cities15000.txt", "alternates_file": None} if demo else {}),
            )
        if command in ("stage-wikidata", "build"):
            if getattr(args, "demo", False):
                wikidata.stage_empty(conn)
            else:
                wikidata.run(conn)
        if command in ("merge", "build"):
            merge.run(conn, force=getattr(args, "force", False))
        if command in ("hierarchy", "build"):
            hierarchy.run(conn)
        if command in ("finalize", "build"):
            finalize.run(conn)
        if command == "enrich":
            from pathlib import Path

            qids: set[str] = set()
            with Path(args.nel_cache).open(encoding="utf-8") as handle:
                for line in handle:
                    for mention in json.loads(line)["mentions"]:
                        qids.update(c["qid"] for c in mention["candidates"][: args.top] if c["score"] >= args.min_score)
            contact = os.environ.get("MS_CONTACT", "").strip() or "local development run"
            with etl_step(conn, "enrich") as stats:
                stats.update(wikidata_api.enrich(conn, sorted(qids), contact, args.limit))
            hierarchy.run(conn)
            finalize.run(conn)
            embeddings.run(conn, {"name", "description", "alias"}, None, rebuild_index=False)
        if command == "embed":
            embeddings.run(conn, set(args.kinds.split(",")), args.limit, args.device)
        if command in ("quality", "eval", "plans"):
            quality_result = quality.run_checks(conn)
            eval_result = search_eval.evaluate(conn) if command in ("eval", "quality") else None
            if command != "plans":
                write_reports(conn, quality_result, eval_result)
            print(
                json.dumps(
                    {
                        "hard_failures": quality_result["hard_failures"],
                        "flags": quality_result["flags"],
                        "search_eval": {k: v for k, v in (eval_result or {}).items() if k != "sample_misses"},
                    },
                    indent=2,
                    default=str,
                )
            )
            if command == "plans":
                results = query_plans.run_all(conn)
                (REPO_ROOT / "docs").mkdir(exist_ok=True)
                (REPO_ROOT / "docs" / "query_plans.md").write_text(
                    query_plans.render_markdown(results, quality_result["places_total"]), encoding="utf-8"
                )
            return 1 if quality_result["hard_failures"] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
