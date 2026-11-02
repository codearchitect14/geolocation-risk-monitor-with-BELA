"""Compare the pipeline with GDELT's own extracted locations (system S3) on current news articles.

GDELT's GKG records list the locations it found in each article (phase 1 stores them). There is no gold for these
articles, so this measures **agreement**, not accuracy: where the two systems differ, either may be right. Article text
is fetched with the polite fetcher (robots.txt honored, per-domain rate limits, snippets only stored).
"""

from __future__ import annotations

import gzip
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

from meridian.config import REPO_ROOT, get_settings
from meridian.db import connect
from meridian.eval.run import DOCS_DIR, RERANKER_PATH
from meridian.linking.config import load_config
from meridian.linking.context import CountryIndex, haversine_km
from meridian.linking.locate import locate
from meridian.linking.nel_client import NelClient
from meridian.linking.pipeline import LinkingPipeline, Stages
from meridian.linking.reranker import Reranker

sys.path.insert(0, str(REPO_ROOT / "data" / "scripts"))
import fetch_article_text as fetcher  # noqa: E402

SEED = 42
CITY_TYPES = {"us_city", "world_city"}
REGION_TYPES = {"us_state", "world_state"}


def load_gkg(sample: int) -> list[dict[str, Any]]:
    root = get_settings().data_dir / "raw" / "news" / "gdelt_gkg"
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*.locations.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                usable = [
                    loc
                    for loc in row["locations"]
                    if loc["lat"] is not None and loc["type"] in CITY_TYPES | REGION_TYPES
                ]
                if usable and row["source_language"] in (None, "eng") and not row["translated"]:
                    records.setdefault(row["url"], {**row, "locations": usable})
    rng = random.Random(SEED)  # noqa: S311
    by_domain: dict[str, dict[str, Any]] = {}
    for row in rng.sample(list(records.values()), min(len(records), sample * 4)):
        by_domain.setdefault(row["domain"], row)
    return list(by_domain.values())[:sample]


def compare(gkg_locations: list[dict[str, Any]], places: list[tuple[float, float]]) -> dict[str, float]:
    """For each GKG location, whether one of our places is close; and the reverse."""
    covered = []
    for loc in gkg_locations:
        radius = 25.0 if loc["type"] in CITY_TYPES else 161.0
        covered.append(any(haversine_km(loc["lat"], loc["lon"], lat, lon) <= radius for lat, lon in places))
    ours = [
        any(
            haversine_km(lat, lon, loc["lat"], loc["lon"]) <= (25.0 if loc["type"] in CITY_TYPES else 161.0)
            for loc in gkg_locations
        )
        for lat, lon in places
    ]
    return {
        "gkg_covered": sum(covered),
        "gkg_total": len(covered),
        "ours_confirmed": sum(ours),
        "ours_total": len(ours),
    }


def run(sample: int = 200) -> dict[str, Any]:
    articles = load_gkg(sample)
    fetch = fetcher.ArticleFetcher(domain_interval=2.0)
    nel = NelClient()
    totals = {"gkg_covered": 0, "gkg_total": 0, "ours_confirmed": 0, "ours_total": 0}
    rows: list[dict[str, Any]] = []
    fetched = failures = 0
    event_close = event_total = 0
    with connect() as conn:
        pipeline = LinkingPipeline(
            conn, nel, load_config(), Reranker.load(RERANKER_PATH), None, CountryIndex.load(conn)
        )
        started = time.perf_counter()
        for article in articles:
            fetched_article = fetch.fetch(article["url"])
            if fetched_article.status != "ok" or not fetched_article.text:
                failures += 1
                continue
            fetched += 1
            result = locate(
                pipeline, fetched_article.text[:6000], title=fetched_article.title or "", stages=Stages(llm=False)
            )
            places = [
                (m.decision.lat, m.decision.lon)
                for m in result.article.mentions
                if m.decision is not None and m.decision.type not in ("country",)
            ]
            counts = compare(article["locations"], places)
            for key, value in counts.items():
                totals[key] += int(value)
            first = article["locations"][0]
            if result.event_location is not None and not result.event_location.country_level:
                event_total += 1
                radius = 25.0 if first["type"] in CITY_TYPES else 161.0
                event_close += (
                    haversine_km(first["lat"], first["lon"], result.event_location.lat, result.event_location.lon)
                    <= radius
                )
            rows.append({"url": article["url"], **counts})
        elapsed = time.perf_counter() - started
    report = {
        "articles_sampled": len(articles),
        "articles_fetched": fetched,
        "fetch_failures": failures,
        "gkg_locations_covered_by_ours": round(totals["gkg_covered"] / max(totals["gkg_total"], 1), 4),
        "our_places_confirmed_by_gkg": round(totals["ours_confirmed"] / max(totals["ours_total"], 1), 4),
        "gkg_locations": totals["gkg_total"],
        "our_places": totals["ours_total"],
        "event_location_matches_first_gkg_location": round(event_close / max(event_total, 1), 4),
        "event_locations": event_total,
        "seconds": round(elapsed, 1),
        "note": "agreement between two automatic systems; disagreement does not identify the wrong one",
    }
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "gkg_agreement.json").write_text(
        json.dumps({"summary": report, "articles": rows}, indent=1) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    print(json.dumps(run(int(sys.argv[1]) if len(sys.argv) > 1 else 200), indent=1))
    _ = Path
