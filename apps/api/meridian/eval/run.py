"""Evaluation harness: python -m meridian.eval <cache-nel|train|evaluate|throughput>.

Writes docs/eval/report.md, CSV files per run under docs/eval/runs/, and public/metrics.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import statistics
import sys
import time
from collections import defaultdict
from typing import Any

import psycopg

from meridian.config import REPO_ROOT, get_settings
from meridian.db import connect
from meridian.eval import systems
from meridian.eval.corpora import Document, load_documents
from meridian.eval.metrics import Gold, error_km, match_spans, summarize
from meridian.geo.names import normalize_name
from meridian.linking import calibration
from meridian.linking.chunk import make_chunks
from meridian.linking.config import load_config
from meridian.linking.context import CountryIndex
from meridian.linking.nel_client import NelClient, NelMention
from meridian.linking.pipeline import LinkingPipeline, Stages
from meridian.linking.reranker import Reranker
from meridian.llm.client import LlmClient

log = logging.getLogger("meridian.eval")
EVAL_DIR = get_settings().data_dir / "processed" / "eval"
RERANKER_PATH = EVAL_DIR / "reranker_geo_config_v1.joblib"
CALIBRATION_PATH = REPO_ROOT / "apps" / "api" / "meridian" / "config" / "calibration_geo_config_v1.json"
DOCS_DIR = REPO_ROOT / "docs" / "eval"
TARGETS = {"hybrid_gain_acc161_ambiguous": 0.05, "bela_passages_per_second": 20.0, "max_llm_share": 0.25}


# -- caching BELA output --------------------------------------------------------------------------------------
def cache_nel(conn: psycopg.Connection[Any], nel: NelClient, checkpoint: str, limit: int | None) -> dict[str, float]:
    docs = load_documents(conn)[: limit or None]
    path = systems.cache_path(EVAL_DIR, checkpoint)
    cache = systems.load_nel_cache(path)
    config = load_config()
    todo = [d for d in docs if (d.corpus, d.doc_id) not in cache]
    passages = 0
    started = time.perf_counter()
    latencies: list[float] = []
    for index, doc in enumerate(todo):
        chunks = make_chunks(doc.text, "en", config.max_chars, config.overlap_sentences)
        t0 = time.perf_counter()
        linked = nel.link([(str(i), c.text) for i, c in enumerate(chunks)])
        latencies.append(time.perf_counter() - t0)
        merged: dict[tuple[int, int], NelMention] = {}
        for i, chunk in enumerate(chunks):
            for m in linked.get(str(i), []):
                shifted = NelMention(
                    m.start + chunk.start,
                    m.end + chunk.start,
                    m.surface,
                    m.qid,
                    m.md_score,
                    m.el_score,
                    m.candidates,
                    m.place_candidates,
                )
                key = (shifted.start, shifted.end)
                if key not in merged or shifted.md_score > merged[key].md_score:
                    merged[key] = shifted
        systems.append_nel_cache(path, doc, sorted(merged.values(), key=lambda m: m.start))
        passages += len(chunks)
        if index % 100 == 0:
            log.info(
                "cached %d of %d documents (%.1f passages/s)",
                index,
                len(todo),
                passages / (time.perf_counter() - started),
            )
    elapsed = time.perf_counter() - started
    summary = {
        "documents": float(len(todo)),
        "passages": float(passages),
        "seconds": round(elapsed, 1),
        "passages_per_second": round(passages / elapsed, 2) if elapsed else 0.0,
        "p50_document_seconds": round(statistics.median(latencies), 3) if latencies else 0.0,
        "p95_document_seconds": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 3) if latencies else 0.0,
    }
    if todo:
        path.with_suffix(".summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return summary


# -- training the re-ranker --------------------------------------------------------------------------------------
def collect_training(
    pipeline: LinkingPipeline, docs: list[Document], cache: dict[tuple[str, str], list[NelMention]]
) -> tuple[list[dict[str, float]], list[int], dict[str, int]]:
    rows: list[dict[str, float]] = []
    labels: list[int] = []
    stats = {"mentions_matched": 0, "mentions_with_positive": 0, "mentions_without_positive": 0}
    for doc in docs:
        nel = cache.get((doc.corpus, doc.doc_id))
        if nel is None:
            continue
        result = pipeline.resolve(doc.text, nel, stages=Stages(llm=False, force_rerank=True))
        gold_spans = [(g.start, g.end) for g in doc.gold]
        matched = match_spans(gold_spans, [(m.start, m.end) for m in result.mentions])
        for gi, mi in matched.items():
            gold, mention = doc.gold[gi], result.mentions[mi]
            stats["mentions_matched"] += 1
            positives = [c for c in mention.candidates if _is_correct(c.place.place_id, c.place.lat, c.place.lon, gold)]
            if not positives:
                stats["mentions_without_positive"] += 1
                continue
            stats["mentions_with_positive"] += 1
            for c in mention.candidates:
                if c.features:
                    rows.append(c.features)
                    labels.append(1 if _is_correct(c.place.place_id, c.place.lat, c.place.lon, gold) else 0)
    return rows, labels, stats


def _is_correct(place_id: int, lat: float, lon: float, gold: Gold) -> bool:
    if gold.place_id is not None:
        return place_id == gold.place_id
    return error_km(gold, lat, lon) <= 10.0


# -- evaluation --------------------------------------------------------------------------------------------------
def ambiguous_surfaces(conn: psycopg.Connection[Any], docs: list[Document]) -> set[str]:
    keys = sorted({normalize_name(g.surface) for d in docs for g in d.gold})
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name_normalized, count(*) FROM places WHERE name_normalized = ANY(%s) GROUP BY 1 HAVING count(*) >= 2",
            (keys,),
        )
        return {r[0] for r in cur.fetchall()}


def run_system(
    name: str,
    docs: list[Document],
    conn: psycopg.Connection[Any],
    pipeline: LinkingPipeline,
    baselines: systems.GazetteerBaselines,
    cache: dict[tuple[str, str], list[NelMention]],
    collect: list[dict[str, Any]],
    llm_counter: dict[str, int] | None = None,
) -> None:
    for doc in docs:
        all_spans: list[tuple[tuple[int, int], Any]] = []
        if name in ("S1", "S2"):
            predictions = []
            for g in doc.gold:
                p = baselines.s1(g) if name == "S1" else baselines.s2(doc, g)
                if p:
                    predictions.append(((g.start, g.end), p))
        else:
            nel = cache.get((doc.corpus, doc.doc_id))
            if nel is None:
                continue
            if name == "S4":
                predictions = systems.bela_alone(pipeline, doc, nel)
            else:
                result = pipeline.resolve(doc.text, nel, stages=systems.STAGES[name])
                predictions = systems.pipeline_predictions(result.mentions)
                all_spans = systems.pipeline_spans(result.mentions)
                if llm_counter is not None:
                    llm_counter["resolved"] = llm_counter.get("resolved", 0) + len(result.resolved)
                    llm_counter["llm"] = llm_counter.get("llm", 0) + sum(
                        1 for m in result.mentions if m.reason.startswith("local model")
                    )
                    llm_counter["mentions"] = llm_counter.get("mentions", 0) + len(result.mentions)
                    for m in result.mentions:
                        llm_counter[f"route_{m.route}"] = llm_counter.get(f"route_{m.route}", 0) + 1
        errors, n_pred, n_matched, chosen = systems.score_document(doc, predictions)
        for gold, error, prediction in zip(doc.gold, errors, chosen, strict=True):
            category, detail = "resolved", ""
            if prediction is None:
                if name in ("S5", "S6"):
                    category, detail = systems.classify_miss(gold, all_spans)
                else:
                    category = "no_candidate" if name in ("S1", "S2") else "span_not_detected"
            collect.append(
                {
                    "system": name,
                    "split": doc.split,
                    "corpus": doc.corpus,
                    "doc_id": doc.doc_id,
                    "surface": gold.surface,
                    "error_km": error,
                    "route": prediction.route if prediction else None,
                    "confidence": prediction.confidence if prediction else None,
                    "predicted": n_pred,
                    "matched": n_matched,
                    "category": category,
                    "detail": detail,
                }
            )


def aggregate(rows: list[dict[str, Any]], selector: Any = None) -> dict[str, float]:
    chosen = [r for r in rows if selector is None or selector(r)]
    errors = [r["error_km"] for r in chosen]
    # detection precision uses per-document counts, counted once per document
    seen: dict[tuple[str, str], tuple[int, int]] = {}
    for r in chosen:
        seen[(r["corpus"], r["doc_id"])] = (r["predicted"], r["matched"])
    predicted = sum(p for p, _ in seen.values())
    matched = sum(m for _, m in seen.values())
    return summarize(errors, len(chosen), predicted, matched)


def write_outputs(rows: list[dict[str, Any]], extra: dict[str, Any]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "runs").mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with (DOCS_DIR / "runs" / f"run-{stamp}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (EVAL_DIR / "last_run.json").write_text(json.dumps(extra, indent=1, default=str) + "\n", encoding="utf-8")


def evaluate(
    conn: psycopg.Connection[Any], nel_client: NelClient | None, checkpoint: str, with_llm: bool
) -> dict[str, Any]:
    docs = load_documents(conn)
    cache = systems.load_nel_cache(systems.cache_path(EVAL_DIR, checkpoint))
    countries = CountryIndex.load(conn)
    reranker = Reranker.load(RERANKER_PATH)
    llm = LlmClient() if with_llm else None
    if llm is not None and not llm.healthy():
        log.warning("language model server not reachable; S6 skipped")
        llm = None
    pipeline = LinkingPipeline(conn, nel_client, load_config(), reranker, llm, countries)
    baselines = systems.GazetteerBaselines(conn, countries)
    calibrators = calibration.load(CALIBRATION_PATH)
    _ = calibrators

    rows: list[dict[str, Any]] = []
    counters: dict[str, dict[str, int]] = {}
    dev = [d for d in docs if d.split == "dev"]
    test = [d for d in docs if d.split == "test"]
    for name in ("S1", "S2", "S4", "S5", "S6"):
        if name == "S6" and llm is None:
            continue
        counters[name] = {}
        started = time.perf_counter()
        run_system(name, test, conn, pipeline, baselines, cache, rows, counters[name])
        counters[name]["seconds"] = int(time.perf_counter() - started)
        log.info("%s done in %ss", name, counters[name]["seconds"])
    # S5 on the dev split feeds calibration
    dev_rows: list[dict[str, Any]] = []
    run_system("S5", dev, conn, pipeline, baselines, cache, dev_rows, {})
    ambiguous = ambiguous_surfaces(conn, test)

    table: dict[str, dict[str, Any]] = {}
    for name in sorted({r["system"] for r in rows}):
        sys_rows = [r for r in rows if r["system"] == name]
        table[name] = {
            "all": aggregate(sys_rows),
            "ambiguous": aggregate(sys_rows, lambda r: normalize_name(r["surface"]) in ambiguous),
            **{
                f"corpus_{c}": aggregate(sys_rows, lambda r, c=c: r["corpus"] == c)
                for c in sorted({r["corpus"] for r in sys_rows})
            },
        }
    # calibration of S5 confidence by route, fitted on dev and checked on test
    cal = fit_calibration(dev_rows, [r for r in rows if r["system"] == "S5"])
    summary_path = systems.cache_path(EVAL_DIR, checkpoint).with_suffix(".summary.json")
    throughput = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    all_rows = rows + dev_rows
    analysis = error_analysis([r for r in rows if r["system"] == ("S6" if "S6" in counters else "S5")])
    write_error_analysis(analysis)
    write_outputs(
        all_rows, {"table": table, "counters": counters, "calibration": cal["report"], "throughput": throughput}
    )
    return {
        "table": table,
        "counters": counters,
        "calibration": cal["report"],
        "throughput": throughput,
        "error_analysis": {k: v for k, v in analysis.items() if k != "examples"},
        "ambiguous_gold": sum(1 for r in rows if r["system"] == "S5" and normalize_name(r["surface"]) in ambiguous),
        "test_gold": sum(1 for r in rows if r["system"] == "S5"),
        "documents": {"dev": len(dev), "test": len(test)},
        "checkpoint": checkpoint,
    }


def error_analysis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Break the test results of the hybrid system down by outcome."""
    total = len(rows)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["category"] == "resolved":
            buckets[
                "resolved_within_25km"
                if r["error_km"] <= 25
                else "resolved_within_161km"
                if r["error_km"] <= 161
                else "resolved_wrong"
            ].append(r)
        else:
            buckets[r["category"]].append(r)
    by_corpus: dict[str, dict[str, int]] = {}
    for r in rows:
        key = "wrong_or_missed" if r["category"] != "resolved" or r["error_km"] > 161 else "right"
        by_corpus.setdefault(r["corpus"], {"right": 0, "wrong_or_missed": 0})[key] += 1
    return {
        "total": total,
        "outcomes": {
            k: {"n": len(v), "share": round(len(v) / total, 4)}
            for k, v in sorted(buckets.items(), key=lambda kv: -len(kv[1]))
        },
        "by_corpus": by_corpus,
        "examples": {
            k: [
                {"surface": r["surface"], "corpus": r["corpus"], "error_km": r["error_km"], "detail": r["detail"]}
                for r in v[:15]
            ]
            for k, v in buckets.items()
        },
    }


def write_error_analysis(analysis: dict[str, Any]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Error analysis (hybrid system, test split)",
        "",
        "| Outcome | Gold toponyms | Share |",
        "|---|---:|---:|",
    ]
    for outcome, v in analysis["outcomes"].items():
        lines.append(f"| {outcome} | {v['n']:,} | {v['share'] * 100:.1f}% |")
    for outcome, examples in analysis["examples"].items():
        if outcome in ("resolved_within_25km",):
            continue
        lines += ["", f"## {outcome}", "", "| Surface | Corpus | Error km | Detail |", "|---|---|---:|---|"]
        for e in examples:
            error = "" if e["error_km"] is None else f"{e['error_km']:,.0f}"
            lines.append(f"| {e['surface']} | {e['corpus']} | {error} | {e['detail']} |")
    (DOCS_DIR / "error_analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def fit_calibration(dev_rows: list[dict[str, Any]], test_rows: list[dict[str, Any]]) -> dict[str, Any]:
    fitted: dict[str, calibration.Calibrator] = {}
    report: dict[str, Any] = {}
    for route in ("accept", "adjudicate", "fallback"):
        dev = [
            (r["confidence"], r["error_km"] <= 25)
            for r in dev_rows
            if r["route"] == route and r["error_km"] is not None and r["confidence"] is not None
        ]
        test = [
            (r["confidence"], r["error_km"] <= 25)
            for r in test_rows
            if r["route"] == route and r["error_km"] is not None and r["confidence"] is not None
        ]
        if len(dev) < 30:
            report[route] = {"skipped": f"only {len(dev)} dev predictions"}
            continue
        calibrator = calibration.Calibrator.fit([s for s, _ in dev], [c for _, c in dev])
        fitted[route] = calibrator
        report[route] = {
            "dev_n": len(dev),
            "test_n": len(test),
            "test_ece_before": calibration.expected_calibration_error([s for s, _ in test], [c for _, c in test])
            if test
            else None,
            "test_ece_after": calibration.expected_calibration_error(
                [calibrator(s) for s, _ in test], [c for _, c in test]
            )
            if test
            else None,
            "reliability_before": calibration.reliability_table([s for s, _ in test], [c for _, c in test])
            if test
            else [],
            "reliability_after": calibration.reliability_table([calibrator(s) for s, _ in test], [c for _, c in test])
            if test
            else [],
        }
    if fitted:
        calibration.save(fitted, CALIBRATION_PATH)
    return {"fitted": fitted, "report": report}


def throughput(articles: int, workers: int, languages: tuple[str, ...]) -> dict[str, Any]:
    """Run the full pipeline (no language model) over real news articles and record speed and failures."""
    import concurrent.futures
    import glob

    import pyarrow.parquet as pq

    texts: list[tuple[str, str, str]] = []
    per_language = articles // len(languages) + 1
    for language in languages:
        for path in sorted(
            glob.glob(
                str(get_settings().data_dir / "raw" / "news" / "cc_news" / language / "**" / "*.parquet"),
                recursive=True,
            )
        ):
            table = pq.read_table(path, columns=["title", "maintext"])
            for title, body in zip(table["title"].to_pylist(), table["maintext"].to_pylist(), strict=True):
                if body and len(body) > 400:
                    texts.append((language, title or "", body[:6000]))
                if sum(1 for t in texts if t[0] == language) >= per_language:
                    break
            if sum(1 for t in texts if t[0] == language) >= per_language:
                break
    texts = texts[:articles]
    latencies: list[float] = []
    failures = 0
    mentions = 0
    routes: dict[str, int] = defaultdict(int)
    nel = NelClient()
    config = load_config()
    reranker = Reranker.load(RERANKER_PATH)

    def work(item: tuple[str, str, str]) -> tuple[float, int, dict[str, int] | None]:
        with connect() as local:
            pipeline = LinkingPipeline(local, nel, config, reranker, None, shared_countries)
            started = time.perf_counter()
            try:
                from meridian.linking.locate import locate

                result = locate(pipeline, item[2], title=item[1], lang=item[0], stages=Stages(llm=False))
            except Exception as exc:  # noqa: BLE001
                log.warning("article failed: %s", exc)
                return time.perf_counter() - started, 0, None
            return time.perf_counter() - started, len(result.article.mentions), dict(result.article.stats["routes"])

    with connect() as conn:
        shared_countries = CountryIndex.load(conn)
    started_all = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for index, (seconds, count, route_counts) in enumerate(pool.map(work, texts)):
            latencies.append(seconds)
            if route_counts is None:
                failures += 1
                continue
            mentions += count
            for route, n in route_counts.items():
                routes[route] += n
            if index % 500 == 0:
                log.info(
                    "%d of %d articles, %.2f articles/s",
                    index,
                    len(texts),
                    (index + 1) / (time.perf_counter() - started_all),
                )
    elapsed = time.perf_counter() - started_all
    latencies.sort()
    ok = len(texts) - failures
    return {
        "articles": len(texts),
        "failures": failures,
        "seconds": round(elapsed, 1),
        "articles_per_second": round(len(texts) / elapsed, 2),
        "mentions_per_article": round(mentions / max(ok, 1), 1),
        "p50_seconds": round(latencies[len(latencies) // 2], 3),
        "p95_seconds": round(latencies[int(0.95 * (len(latencies) - 1))], 3),
        "workers": workers,
        "languages": list(languages),
        "routes": dict(routes),
        "passed": failures == 0 and len(texts) >= articles,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m meridian.eval")
    sub = parser.add_subparsers(dest="command", required=True)
    cache_p = sub.add_parser("cache-nel")
    cache_p.add_argument("--checkpoint", default="model_wiki.ckpt")
    cache_p.add_argument("--limit", type=int)
    sub.add_parser("train")
    ev = sub.add_parser("evaluate")
    ev.add_argument("--checkpoint", default="model_wiki.ckpt")
    ev.add_argument("--no-llm", action="store_true")
    an = sub.add_parser("analyze", help="error analysis from the latest saved run")
    an.add_argument("--system", default="S6")
    tp = sub.add_parser("throughput")
    tp.add_argument("--articles", type=int, default=10_000)
    tp.add_argument("--workers", type=int, default=4)
    tp.add_argument("--languages", default="en,es,de")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with connect() as conn:
        if args.command == "cache-nel":
            nel = NelClient()
            if not nel.healthy():
                print("NEL service is not running", file=sys.stderr)
                return 1
            print(json.dumps(cache_nel(conn, nel, args.checkpoint, args.limit), indent=1))
        elif args.command == "train":
            docs = [d for d in load_documents(conn) if d.split == "dev"]
            cache = systems.load_nel_cache(systems.cache_path(EVAL_DIR, "model_wiki.ckpt"))
            pipeline = LinkingPipeline(conn, None, load_config(), Reranker(None, "rules_v1"))
            rows, labels, stats = collect_training(pipeline, docs, cache)
            report = Reranker.train(rows, labels, "reranker_v1_geo_config_v1", RERANKER_PATH)
            print(json.dumps({**stats, **report}, indent=1))
        elif args.command == "analyze":
            latest = sorted((DOCS_DIR / "runs").glob("run-*.csv"))[-1]
            with latest.open(encoding="utf-8") as handle:
                saved = [r for r in csv.DictReader(handle) if r["system"] == args.system and r["split"] == "test"]
            for r in saved:
                r["error_km"] = float(r["error_km"]) if r["error_km"] else None
            write_error_analysis(error_analysis(saved))
            print(f"wrote {DOCS_DIR / 'error_analysis.md'} from {latest.name} ({len(saved)} gold toponyms)")
        elif args.command == "throughput":
            report = throughput(args.articles, args.workers, tuple(args.languages.split(",")))
            DOCS_DIR.mkdir(parents=True, exist_ok=True)
            (DOCS_DIR / "throughput.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=1))
        elif args.command == "evaluate":
            nel = NelClient()
            result = evaluate(conn, nel, args.checkpoint, with_llm=not args.no_llm)
            (EVAL_DIR / "result.json").write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
            print(json.dumps({k: v for k, v in result.items() if k != "table"}, indent=1, default=str)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
