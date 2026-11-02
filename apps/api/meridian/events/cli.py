"""Command line entry point: python -m meridian.events <command>."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any

from meridian.config import get_settings
from meridian.db import connect
from meridian.events import service, status
from meridian.events.config import load_events_config
from meridian.events.normalizers.nws import ZoneResolver

DEMO_SLUG = "illustrative-demo"


def raw_files(kind: str, pattern: str) -> list[Path]:
    return sorted((get_settings().data_dir / "raw" / "hazards" / kind).glob(pattern))


def demo_tenant(conn: Any, assets: int, seed: int) -> dict[str, Any]:
    """A synthetic tenant whose sites are sampled from the place knowledge base. Labeled illustrative everywhere."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM tenants WHERE slug = %s", (DEMO_SLUG,))
        cur.execute(
            "INSERT INTO tenants (name, slug, industry, is_demo) VALUES (%s, %s, %s, true) RETURNING id",
            ("Illustrative demo tenant (synthetic data)", DEMO_SLUG, "illustrative"),
        )
        tenant = cur.fetchone()[0]
        cur.execute(
            """SELECT name, country_code, lat, lon FROM places
                WHERE type IN ('city', 'town') AND population >= 100000 AND lat IS NOT NULL ORDER BY id"""
        )
        pool = cur.fetchall()
        picks = random.Random(seed).sample(pool, min(assets, len(pool)))  # noqa: S311 - synthetic sampling
        rng = random.Random(seed + 1)  # noqa: S311
        for name, cc, lat, lon in picks:
            cur.execute(
                """INSERT INTO assets (tenant_id, name, type, geom, criticality, country_code, tags)
                   VALUES (%s, %s, 'site', ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s)""",
                (tenant, f"{name} site (synthetic)", lon, lat, rng.choice([2, 3, 3, 4, 5]), cc, ["synthetic"]),
            )
    conn.commit()
    return {"tenant": str(tenant), "assets": len(picks)}


KEYWORDS = (
    "fire", "blaze", "explosion", "blast", "spill", "flood", "earthquake", "quake", "storm", "hurricane", "typhoon",
    "wildfire", "strike", "blockade", "outage", "collapse", "evacuat", "crash", "derail", "riot", "outbreak",
    "incendio", "explosión", "inundación", "terremoto", "huelga", "brand", "explosion", "überschwemmung", "erdbeben",
)  # fmt: skip


def replay_news(conn: Any, path: Path, limit: int, seed: int, use_llm_linking: bool) -> dict[str, Any]:
    """Run real CC-News articles (disruption keywords in the headline, testing use only) through the full news pipeline."""
    import pandas as pd

    from meridian.events.ingest import EventIngestor
    from meridian.events.news import Article, NewsIngestor
    from meridian.linking.config import load_config
    from meridian.linking.context import CountryIndex
    from meridian.linking.nel_client import NelClient
    from meridian.linking.pipeline import LinkingPipeline, Stages
    from meridian.linking.reranker import Reranker
    from meridian.llm.client import LlmClient

    frame = pd.read_parquet(path)
    frame["date_publish"] = pd.to_datetime(frame["date_publish"], errors="coerce")
    frame = frame[frame["date_publish"].between("2005-01-01", "2026-12-31")]
    mask = frame["title"].str.lower().str.contains("|".join(KEYWORDS), na=False)
    pick = frame[mask].sample(n=min(limit, int(mask.sum())), random_state=seed).sort_values("date_publish")
    cfg = load_events_config()
    nel, llm = NelClient(), LlmClient()
    reranker_path = get_settings().data_dir / "processed" / "eval" / "reranker_geo_config_v1.joblib"
    pipeline = LinkingPipeline(conn, nel, load_config(), Reranker.load(reranker_path), llm, CountryIndex.load(conn))
    ingest = NewsIngestor(conn, cfg, pipeline, llm, EventIngestor(conn, cfg, nel.embed), Stages(llm=use_llm_linking))
    statuses: dict[str, int] = {}
    actions: dict[str, int] = {}
    types: dict[str, int] = {}
    for row in pick.itertuples():
        published = pd.Timestamp(row.date_publish).to_pydatetime().replace(tzinfo=dt.UTC)
        result = ingest.process(Article(row.url, row.title, row.maintext or "", published))
        conn.commit()
        statuses[result.status] = statuses.get(result.status, 0) + 1
        if result.outcome:
            actions[result.outcome.action] = actions.get(result.outcome.action, 0) + 1
            if result.classification:
                types[result.classification.event_type] = types.get(result.classification.event_type, 0) + 1
    return {"articles": len(pick), "statuses": statuses, "event_actions": actions, "event_types": types}


def report(conn: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    queries = {
        "events_by_type": "SELECT type, count(*) FROM events GROUP BY 1 ORDER BY 2 DESC",
        "events_by_status": "SELECT status, count(*) FROM events GROUP BY 1 ORDER BY 2 DESC",
        "events_by_confirmation": "SELECT confirmation, count(*) FROM events GROUP BY 1 ORDER BY 2 DESC",
        "sources_by_kind": "SELECT source_kind, count(*) FROM event_sources GROUP BY 1 ORDER BY 2 DESC",
        "exposures_by_level": "SELECT level, count(*) FROM exposures GROUP BY 1 ORDER BY 2 DESC",
        "alerts_by_level": "SELECT level, count(*) FROM alerts GROUP BY 1 ORDER BY 2 DESC",
        "alerts_by_status": "SELECT status, count(*) FROM alerts GROUP BY 1 ORDER BY 2 DESC",
    }
    with conn.cursor() as cur:
        for key, sql in queries.items():
            cur.execute(sql)
            out[key] = {str(k): v for k, v in cur.fetchall()}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m meridian.events")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("ingest-usgs", "ingest-nws", "ingest-reliefweb"):
        p = sub.add_parser(name)
        p.add_argument("--glob", default="*.jsonl")
        p.add_argument("--replay", action="store_true", help="score each record as of its own time")
    sub.choices["ingest-nws"].add_argument("--no-fetch", action="store_true", help="use cached zones only")
    firms = sub.add_parser("ingest-firms")
    firms.add_argument("--glob", default="*.csv")
    firms.add_argument("--replay", action="store_true")
    sub.add_parser("update-status")
    demo = sub.add_parser("demo-tenant")
    demo.add_argument("--assets", type=int, default=150)
    demo.add_argument("--seed", type=int, default=7)
    replay = sub.add_parser("replay-news", help="testing use only: CC-News slice through the news pipeline")
    replay.add_argument("--path", type=Path, required=True)
    replay.add_argument("--limit", type=int, default=150)
    replay.add_argument("--seed", type=int, default=3)
    replay.add_argument("--no-llm-linking", action="store_true")
    sub.add_parser("report")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = load_events_config()
    with connect() as conn:
        if args.command == "ingest-usgs":
            run = service.ingest_usgs(conn, cfg, raw_files("usgs", args.glob), replay=args.replay)
        elif args.command == "ingest-nws":
            resolver = ZoneResolver(conn)
            run = service.ingest_nws(conn, cfg, raw_files("nws", args.glob), resolver, replay=args.replay)
        elif args.command == "ingest-reliefweb":
            run = service.ingest_reliefweb(conn, cfg, raw_files("reliefweb", args.glob), replay=args.replay)
        elif args.command == "ingest-firms":
            run = None
            for path in raw_files("firms", args.glob):
                run = service.ingest_firms(conn, cfg, path.read_text(encoding="utf-8"), replay=args.replay)
            if run is None:
                print(json.dumps({"error": "no FIRMS files; set FIRMS_MAP_KEY and run data/scripts/pull_firms.py"}))
                return 1
        elif args.command == "update-status":
            print(json.dumps(status.refresh_all(conn, cfg, dt.datetime.now(dt.UTC))))
            conn.commit()
            return 0
        elif args.command == "demo-tenant":
            print(json.dumps(demo_tenant(conn, args.assets, args.seed)))
            return 0
        elif args.command == "replay-news":
            print(json.dumps(replay_news(conn, args.path, args.limit, args.seed, not args.no_llm_linking), indent=2))
            return 0
        else:
            print(json.dumps(report(conn), indent=2))
            return 0
        assert run is not None
        print(json.dumps(run.summary(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
