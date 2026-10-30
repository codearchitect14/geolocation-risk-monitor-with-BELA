"""Command line entry point: python -m meridian.etl <command>."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from meridian.config import REPO_ROOT, get_settings
from meridian.db import connect
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
    sub.choices["merge"].add_argument("--force", action="store_true")
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
            geonames.run(
                conn,
                min_population=args.min_population,
                include_minor_facilities=getattr(args, "include_minor_facilities", False),
            )
        if command in ("stage-wikidata", "build"):
            wikidata.run(conn)
        if command in ("merge", "build"):
            merge.run(conn, force=getattr(args, "force", False))
        if command in ("hierarchy", "build"):
            hierarchy.run(conn)
        if command in ("finalize", "build"):
            finalize.run(conn)
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
