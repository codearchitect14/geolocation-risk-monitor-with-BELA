"""Recall and latency of the place embedding index for several hnsw.ef_search values.

    python infra/perf/hnsw_sweep.py [--queries 40] [--k 10]

Query vectors are existing place embeddings picked at random. Ground truth is an exact scan (index scans disabled).
Recall is the share of the exact top-k rows that the index also returns.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from meridian.db import connect  # noqa: E402

SQL = "SELECT id FROM place_embeddings ORDER BY embedding <=> %s::vector LIMIT %s"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--values", default="10,20,40,60,100,200,400")
    args = ap.parse_args()
    conn = connect()
    total = conn.execute("SELECT max(id) FROM place_embeddings").fetchone()
    assert total is not None
    vectors = [
        r[0]
        for r in conn.execute(
            "SELECT embedding::text FROM place_embeddings WHERE id IN "
            "(SELECT (random() * %s)::bigint FROM generate_series(1, %s)) LIMIT %s",
            (total[0], args.queries * 2, args.queries),
        ).fetchall()
    ]
    exact: list[set[int]] = []
    conn.execute("BEGIN")
    conn.execute("SET LOCAL enable_indexscan = off")
    conn.execute("SET LOCAL max_parallel_workers_per_gather = 4")
    for v in vectors:
        exact.append({r[0] for r in conn.execute(SQL, (v, args.k)).fetchall()})
    conn.rollback()
    results = []
    for ef in (int(x) for x in args.values.split(",")):
        conn.execute("BEGIN")
        conn.execute(f"SET LOCAL hnsw.ef_search = {ef}")  # noqa: S608 - integer
        times, hits = [], 0
        for v, truth in zip(vectors, exact, strict=True):
            t0 = time.perf_counter()
            got = {r[0] for r in conn.execute(SQL, (v, args.k)).fetchall()}
            times.append((time.perf_counter() - t0) * 1000)
            hits += len(got & truth)
        conn.rollback()
        times.sort()
        results.append(
            {
                "ef_search": ef,
                "recall_at_k": round(hits / (len(vectors) * args.k), 4),
                "p50_ms": round(times[len(times) // 2], 2),
                "p95_ms": round(times[min(len(times) - 1, int(len(times) * 0.95))], 2),
            }
        )
        print(json.dumps(results[-1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
