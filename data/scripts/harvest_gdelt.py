"""Harvest news metadata from the GDELT DOC 2.0 API into data/raw/news/gdelt.

For every topic and language in config/gdelt_queries.yaml one ArtList query is sent,
at most one request per five seconds. New articles (by URL) are appended to one JSONL
file per UTC day. Only metadata is stored: title, URL, outlet domain, language,
country and timestamp. Publishers keep copyright.

Live mode uses a rolling timespan. Backfill mode walks day windows with
startdatetime and enddatetime (the API serves roughly the last three months).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

import common

SOURCE_ID = "gdelt_doc"
API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
CONFIG_PATH = Path(__file__).resolve().parent / "config" / "gdelt_queries.yaml"
MIN_INTERVAL_SECONDS = 5.5
MAX_RECORDS = 250
MAX_CONSECUTIVE_RATE_LIMITS = 2
RATE_LIMIT_BACKOFF_SECONDS = 30.0

log = common.get_logger("harvest_gdelt")


def quote_term(term: str) -> str:
    return f'"{term}"' if " " in term or "-" in term else term


def build_query(terms: list[str], sourcelang: str) -> str:
    group = " OR ".join(quote_term(t) for t in terms)
    return f"({group}) sourcelang:{sourcelang}"


def load_matrix(path: Path = CONFIG_PATH) -> list[dict[str, str]]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    languages: dict[str, Any] = config["languages"]
    jobs: list[dict[str, str]] = []
    for topic, by_language in config["topics"].items():
        for language, spec in languages.items():
            terms = by_language.get(language)
            if not terms:
                raise ValueError(f"topic {topic} has no terms for {language}")
            jobs.append(
                {
                    "topic": topic,
                    "language": language,
                    "query": build_query(terms, spec["sourcelang"]),
                }
            )
    return jobs


def parse_seendate(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC)
    except ValueError:
        return None


def parse_articles(response: httpx.Response) -> list[dict[str, Any]] | None:
    """Return the article list, or None when the body is not a usable JSON result."""
    text = response.text.strip()
    if not text:
        return []  # the API returns an empty body for no matches
    try:
        payload = json.loads(text)
    except ValueError:
        log.warning("non-JSON response: %s", text[:120])
        return None
    articles = payload.get("articles", []) if isinstance(payload, dict) else None
    return articles if isinstance(articles, list) else None


def to_record(article: dict[str, Any], job: dict[str, str], harvested_at: str) -> dict[str, Any] | None:
    url = article.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    seen = parse_seendate(article.get("seendate"))
    return {
        "url": url,
        "title": article.get("title"),
        "domain": article.get("domain"),
        "language": article.get("language"),
        "source_country": article.get("sourcecountry"),
        "seen_at": seen.isoformat().replace("+00:00", "Z") if seen else None,
        "topics": [job["topic"]],
        "query_language": job["language"],
        "harvested_at": harvested_at,
    }


def day_file(directory: Path, record: dict[str, Any]) -> Path:
    stamp = record.get("seen_at") or record["harvested_at"]
    return directory / f"{stamp[:10]}.jsonl"


def existing_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {r["url"] for r in common.iter_jsonl(path) if "url" in r}


def store(records: dict[str, dict[str, Any]], directory: Path) -> int:
    by_file: dict[Path, list[dict[str, Any]]] = {}
    for record in records.values():
        by_file.setdefault(day_file(directory, record), []).append(record)
    written = 0
    for path, items in by_file.items():
        known = existing_urls(path)
        fresh = [r for r in items if r["url"] not in known]
        written += common.append_jsonl(path, fresh)
    return written


def run_jobs(
    client: httpx.Client,
    jobs: list[dict[str, str]],
    params_extra: dict[str, str],
    limiter: common.RateLimiter,
) -> dict[str, Any]:
    harvested_at = common.iso_now()
    collected: dict[str, dict[str, Any]] = {}
    capped = failed = rate_limited = 0
    aborted = False
    for job in jobs:
        if rate_limited >= MAX_CONSECUTIVE_RATE_LIMITS:
            aborted = True
            log.error("rate limited %d times in a row, abandoning this pass", rate_limited)
            break
        limiter.wait("gdelt")
        params = {
            "query": job["query"],
            "mode": "ArtList",
            "format": "json",
            "maxrecords": str(MAX_RECORDS),
            "sort": "DateDesc",
            **params_extra,
        }
        try:
            response = common.request_with_retry(
                client,
                "GET",
                API_URL,
                params=params,
                logger=log,
                retries=1,
                backoff=RATE_LIMIT_BACKOFF_SECONDS,
            )
        except httpx.HTTPError as exc:
            log.warning("query failed (%s/%s): %s", job["topic"], job["language"], exc)
            failed += 1
            rate_limited += 1 if _is_rate_limit(exc) else 0
            continue
        rate_limited = 0
        articles = parse_articles(response) if response.status_code == 200 else None
        if articles is None:
            failed += 1
            continue
        if len(articles) >= MAX_RECORDS:
            capped += 1
            log.warning("result cap reached for %s/%s", job["topic"], job["language"])
        for article in articles:
            record = to_record(article, job, harvested_at)
            if record is None:
                continue
            if record["url"] in collected:
                topics = collected[record["url"]]["topics"]
                if job["topic"] not in topics:
                    topics.append(job["topic"])
            else:
                collected[record["url"]] = record
    written = store(collected, common.raw_dir("news", "gdelt"))
    return {
        "queries": len(jobs),
        "failed": failed,
        "capped": capped,
        "articles_seen": len(collected),
        "written": written,
        "aborted": int(aborted),
    }


def _is_rate_limit(exc: httpx.HTTPError) -> bool:
    response = getattr(exc, "response", None)
    return bool(response is not None and response.status_code == 429)


def merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    return {k: a.get(k, 0) + b.get(k, 0) for k in set(a) | set(b)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timespan", default="3h", help="live mode window, for example 3h or 1d")
    parser.add_argument("--start", type=common.parse_date, help="backfill start date")
    parser.add_argument("--end", type=common.parse_date, help="backfill end date (inclusive)")
    parser.add_argument("--topic", action="append", help="limit to these topics")
    parser.add_argument("--language", action="append", help="limit to these query languages")
    parser.add_argument("--dry-run", action="store_true", help="print the query matrix and exit")
    args = parser.parse_args(argv)

    jobs = load_matrix()
    if args.topic:
        jobs = [j for j in jobs if j["topic"] in args.topic]
    if args.language:
        jobs = [j for j in jobs if j["language"] in args.language]
    if args.dry_run:
        for job in jobs:
            print(f"{job['topic']:16} {job['language']:11} {job['query']}")
        return 0

    limiter = common.RateLimiter(MIN_INTERVAL_SECONDS)
    try:
        with common.make_client(timeout=90.0) as client:
            if args.start:
                stats: dict[str, Any] = {}
                for day in common.date_range(args.start, args.end or common.utcnow().date()):
                    window = {
                        "startdatetime": day.strftime("%Y%m%d000000"),
                        "enddatetime": day.strftime("%Y%m%d235959"),
                    }
                    stats = merge(stats, run_jobs(client, jobs, window, limiter))
            else:
                stats = run_jobs(client, jobs, {"timespan": args.timespan}, limiter)
    except Exception as exc:
        log.error("gdelt harvest failed: %s", exc)
        common.write_status("gdelt", False, {"error": str(exc)})
        return 1
    ok = stats["failed"] < stats["queries"]
    log.info("gdelt done: %s", stats)
    common.write_status("gdelt", ok, stats if ok else {"error": "all queries failed", **stats})
    common.record_harvest(SOURCE_ID, stats)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
