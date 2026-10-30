"""Evaluate gazetteer search on a fixed set of place names with known GeoNames IDs.

The test set is drawn from the EUPEG corpora (LGL, TR-News, GeoWebNews): unique pairs of
surface form and GeoNames ID whose ID exists in the place table. A seeded sample of 1,000
pairs is searched without any context (no country hint), which is the hardest setting.
The baseline is the most populous exact name match.
"""

from __future__ import annotations

import json
import logging
import random
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import psycopg

from meridian.config import get_settings
from meridian.geo.names import normalize_name
from meridian.geo.search import search_by_embedding, search_places

log = logging.getLogger("meridian.etl.search_eval")

CORPORA = ("lgl", "tr-news", "geowebnews")
SAMPLE_SIZE = 1000
SEED = 42
TARGET_TOP5 = 0.85


def gold_pairs(root: Path | None = None) -> tuple[list[tuple[str, int, str]], int]:
    """Return unique (surface, geonames_id, corpus) pairs and the number of pairs before filtering."""
    base = root or get_settings().data_dir / "raw" / "eval" / "eupeg"
    seen: dict[tuple[str, int], str] = {}
    for corpus in CORPORA:
        path = base / f"{corpus}.jsonl"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                for toponym in json.loads(line)["toponyms"]:
                    gid = toponym.get("geonames_id")
                    if gid and str(gid).isdigit() and toponym["surface"].strip():
                        seen.setdefault((toponym["surface"].strip(), int(gid)), corpus)
    pairs = sorted((s, g, c) for (s, g), c in seen.items())
    return pairs, len(pairs)


def vector_scores(
    conn: psycopg.Connection[Any], sample: list[tuple[str, int, str]], known: dict[int, tuple[int, str]]
) -> dict[str, Any]:
    """Top-1 and top-5 for vector-only retrieval and for trigram search combined with vectors.

    Skipped when too few places are embedded for the comparison to mean anything.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT count(DISTINCT place_id) FROM place_embeddings")
        row = cur.fetchone()
        cur.execute("SELECT count(*) FROM places")
        total_row = cur.fetchone()
    embedded, total = (int(row[0]) if row else 0), (int(total_row[0]) if total_row else 0)
    if total == 0 or embedded < 0.9 * total:
        return {"skipped": f"only {embedded:,} of {total:,} places are embedded"}
    from meridian.etl.embeddings import load_model

    model = load_model()
    vectors = model.encode(
        [s for s, _, _ in sample], batch_size=128, normalize_embeddings=True, show_progress_bar=False
    )
    vec_top1 = vec_top5 = hybrid_top5 = 0
    for (surface, gid, _), vector in zip(sample, vectors, strict=True):
        expected = known[gid][0]
        vec_ids = [pid for pid, _ in search_by_embedding(conn, vector, k=5)]
        vec_top1 += bool(vec_ids) and vec_ids[0] == expected
        vec_top5 += expected in vec_ids
        trigram_ids = [h.place_id for h in search_places(conn, surface, k=5)]
        hybrid_top5 += expected in (trigram_ids[:3] + [i for i in vec_ids if i not in trigram_ids[:3]])[:5]
    n = len(sample)
    return {
        "vector_only_top1": round(vec_top1 / n, 4),
        "vector_only_top5": round(vec_top5 / n, 4),
        "hybrid_top5": round(hybrid_top5 / n, 4),
    }


def evaluate(
    conn: psycopg.Connection[Any], sample_size: int = SAMPLE_SIZE, with_vectors: bool = True
) -> dict[str, Any]:
    pairs, total_pairs = gold_pairs()
    if not pairs:
        return {"error": "no EUPEG corpora found; run make data-eupeg"}
    with conn.cursor() as cur:
        cur.execute("SELECT id, geonames_id, type FROM places WHERE geonames_id = ANY(%s)", ([g for _, g, _ in pairs],))
        known = {int(gid): (int(pid), ptype) for pid, gid, ptype in cur.fetchall()}
    in_kb = [p for p in pairs if p[1] in known]
    rng = random.Random(SEED)  # noqa: S311
    sample = rng.sample(in_kb, min(sample_size, len(in_kb)))

    with conn.cursor() as cur:
        cur.execute("SELECT name_normalized, count(*) FROM places GROUP BY 1 HAVING count(*) > 1")
        ambiguous_names = {n for n, _ in cur.fetchall()}

    hits = {"top1": 0, "top5": 0, "baseline_top1": 0}
    by_corpus: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    ambiguous = [0, 0]
    misses: list[dict[str, Any]] = []
    latencies: list[float] = []
    for surface, gid, corpus in sample:
        expected, expected_type = known[gid]
        started = time.perf_counter()
        results = search_places(conn, surface, k=5)
        latencies.append((time.perf_counter() - started) * 1000)
        ids = [h.place_id for h in results]
        top5 = expected in ids
        top1 = bool(ids) and ids[0] == expected
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM places WHERE name_normalized = %s ORDER BY population DESC NULLS LAST, id LIMIT 1",
                (normalize_name(surface),),
            )
            row = cur.fetchone()
        hits["baseline_top1"] += bool(row and row[0] == expected)
        hits["top1"] += top1
        hits["top5"] += top5
        by_corpus[corpus][0] += top5
        by_corpus[corpus][1] += 1
        by_type[expected_type][0] += top5
        by_type[expected_type][1] += 1
        if normalize_name(surface) in ambiguous_names:
            ambiguous[0] += top5
            ambiguous[1] += 1
        if not top5 and len(misses) < 25:
            misses.append(
                {
                    "surface": surface,
                    "expected_geonames_id": gid,
                    "expected_type": expected_type,
                    "returned": [f"{h.name} ({h.type}, {h.country_code})" for h in results[:3]],
                }
            )
    n = len(sample)
    latencies.sort()
    vectors = vector_scores(conn, sample, known) if with_vectors else {"skipped": "disabled"}
    return {
        "vectors": vectors,
        "gold_pairs_total": total_pairs,
        "gold_pairs_in_knowledge_base": len(in_kb),
        "gold_kb_coverage": round(len(in_kb) / max(total_pairs, 1), 4),
        "sample_size": n,
        "top1": round(hits["top1"] / max(n, 1), 4),
        "top5": round(hits["top5"] / max(n, 1), 4),
        "baseline_most_populous_exact_top1": round(hits["baseline_top1"] / max(n, 1), 4),
        "target_top5": TARGET_TOP5,
        "target_met": hits["top5"] / max(n, 1) >= TARGET_TOP5,
        "top5_ambiguous_names": round(ambiguous[0] / ambiguous[1], 4) if ambiguous[1] else None,
        "ambiguous_sample": ambiguous[1],
        "top5_by_corpus": {k: round(v[0] / v[1], 4) for k, v in sorted(by_corpus.items())},
        "top5_by_type": {k: round(v[0] / v[1], 4) for k, v in sorted(by_type.items())},
        "latency_ms": {
            "p50": round(statistics.median(latencies), 1),
            "p95": round(latencies[int(0.95 * (len(latencies) - 1))], 1),
        }
        if latencies
        else {},
        "sample_misses": misses,
    }
