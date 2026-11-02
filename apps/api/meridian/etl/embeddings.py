"""Compute bge-m3 embeddings for place names, aliases, and descriptions.

Texts follow a "title plus description" shape so that same-name places differ in the
vector space:
  name         "Springfield (city), Illinois, United States"
  alias        "Springfield, Illinois, United States" built from an alternate name
  description  "Springfield: capital of the U.S. state of Illinois"

The job is resumable: places that already have a row of a kind are skipped. Places are
processed in descending population so a partial run still covers the most important ones.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import psycopg

from meridian.config import get_settings
from meridian.db import etl_step

log = logging.getLogger("meridian.etl.embeddings")

TYPE_LABELS = {
    "railway_station": "railway station",
    "power_station": "power station",
    "border_crossing": "border crossing",
    "military_base": "military base",
    "admin1": "region",
    "admin2": "district",
    "admin_region": "district",
}
MAX_ALIASES = 3
ALIAS_MIN_POPULATION = 100_000
MAX_SEQ_LENGTH = 64


def type_label(place_type: str) -> str:
    return TYPE_LABELS.get(place_type, place_type.replace("_", " "))


def context(admin1: str | None, country: str | None) -> str:
    return ", ".join(part for part in (admin1, country) if part)


def name_text(name: str, place_type: str, admin1: str | None, country: str | None) -> str:
    place = f"{name} ({type_label(place_type)})"
    return f"{place}, {context(admin1, country)}" if context(admin1, country) else place


def alias_text(alias: str, admin1: str | None, country: str | None) -> str:
    return f"{alias}, {context(admin1, country)}" if context(admin1, country) else alias


def description_text(name: str, description: str) -> str:
    return f"{name}: {description}"


BASE_SQL = """
SELECT p.id, p.name, p.type, p.admin1_name, c.name, p.description, p.population
  FROM places p LEFT JOIN ref_country_info c ON c.iso2 = p.country_code
 WHERE {where}
 ORDER BY p.population DESC NULLS LAST, p.id
 {limit}
"""


def pending_texts(
    conn: psycopg.Connection[Any], kinds: set[str], limit: int | None
) -> Iterator[tuple[int, str, str | None, str]]:
    """Yield (place_id, kind, language, text) for places missing an embedding of that kind."""
    limit_sql = f"LIMIT {int(limit)}" if limit else ""  # noqa: S608
    if "name" in kinds:
        where = "NOT EXISTS (SELECT 1 FROM place_embeddings e WHERE e.place_id = p.id AND e.kind = 'name')"
        with conn.cursor(name="pending_names", withhold=True) as cur:
            cur.itersize = 20_000
            cur.execute(BASE_SQL.format(where=where, limit=limit_sql))
            for pid, name, ptype, admin1, country, _desc, _pop in cur:
                yield pid, "name", None, name_text(name, ptype, admin1, country)
    if "description" in kinds:
        where = (
            "p.description IS NOT NULL AND NOT EXISTS (SELECT 1 FROM place_embeddings e "
            "WHERE e.place_id = p.id AND e.kind = 'description')"
        )
        with conn.cursor(name="pending_desc", withhold=True) as cur:
            cur.itersize = 20_000
            cur.execute(BASE_SQL.format(where=where, limit=limit_sql))
            for pid, name, _t, _a, _c, desc, _pop in cur:
                yield pid, "description", "en", description_text(name, desc)
    if "alias" in kinds:
        where = (
            f"p.population >= {ALIAS_MIN_POPULATION} AND NOT EXISTS "  # noqa: S608
            "(SELECT 1 FROM place_embeddings e WHERE e.place_id = p.id AND e.kind = 'alias')"
        )
        with conn.cursor(name="pending_alias", withhold=True) as cur, conn.cursor() as aliases:
            cur.itersize = 5_000
            cur.execute(BASE_SQL.format(where=where, limit=limit_sql))
            for pid, _name, _t, admin1, country, _desc, _pop in cur:
                aliases.execute(
                    """SELECT alias, language FROM place_aliases WHERE place_id = %s
                        ORDER BY (language = 'en') DESC NULLS LAST, (type = 'preferred') DESC, length(alias)
                        LIMIT %s""",
                    (pid, MAX_ALIASES),
                )
                for alias, language in aliases.fetchall():
                    yield pid, "alias", language, alias_text(alias, admin1, country)


def vector_literal(values: Any) -> str:
    return "[" + ",".join(f"{float(v):.6g}" for v in values) + "]"


def write_embeddings(conn: psycopg.Connection[Any], rows: list[tuple[int, str, str | None, str, str, Any]]) -> None:
    """Binary COPY with native vector values (about 20 times faster than the text format)."""
    import numpy as np
    from pgvector.psycopg import register_vector

    register_vector(conn)
    with (
        conn.cursor() as cur,
        cur.copy(
            "COPY place_embeddings (place_id, kind, language, text, model, embedding) FROM STDIN WITH (FORMAT BINARY)"
        ) as copy,
    ):
        copy.set_types(["int8", "text", "text", "text", "text", "vector"])
        for place_id, kind, language, text, model_name, vector in rows:
            copy.write_row((place_id, kind, language, text, model_name, np.asarray(vector, dtype=np.float32)))


def load_model(device: str | None = None) -> Any:
    import torch
    from sentence_transformers import SentenceTransformer

    chosen = device or ("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
    model = SentenceTransformer(get_settings().embedding_model, device=chosen)
    model.max_seq_length = MAX_SEQ_LENGTH
    if chosen != "cpu":
        model.half()
    log.info("loaded %s on %s", get_settings().embedding_model, chosen)
    return model


def embed(
    conn: psycopg.Connection[Any],
    kinds: set[str],
    limit: int | None = None,
    batch_size: int = 128,
    chunk: int = 4096,
    device: str | None = None,
) -> dict[str, int]:
    model = load_model(device)
    model_name = get_settings().embedding_model
    done: dict[str, int] = {}
    buffer: list[tuple[int, str, str | None, str]] = []
    started = time.monotonic()

    def flush() -> None:
        if not buffer:
            return
        t0 = time.monotonic()
        vectors = model.encode(
            [row[3] for row in buffer], batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False
        )
        t1 = time.monotonic()
        write_embeddings(
            conn,
            [
                (pid, kind, lang, text, model_name, vec)
                for (pid, kind, lang, text), vec in zip(buffer, vectors, strict=True)
            ],
        )
        t2 = time.monotonic()
        conn.commit()
        for row in buffer:
            done[row[1]] = done.get(row[1], 0) + 1
        total = sum(done.values())
        log.info(
            "embedded %d texts (%.0f/s); chunk: encode %.1fs, format+copy %.1fs, commit %.1fs",
            total,
            total / (time.monotonic() - started),
            t1 - t0,
            t2 - t1,
            time.monotonic() - t2,
        )
        buffer.clear()

    for item in pending_texts(conn, kinds, limit):
        buffer.append(item)
        if len(buffer) >= chunk:
            flush()
    flush()
    return done


def drop_index(conn: psycopg.Connection[Any]) -> None:
    """Remove the HNSW index before a bulk load. Incremental graph updates cost milliseconds per row."""
    with conn.cursor() as cur:
        cur.execute("DROP INDEX IF EXISTS place_embeddings_hnsw")
    conn.commit()


def build_index(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute("SET maintenance_work_mem = '2GB'")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS place_embeddings_hnsw ON place_embeddings "
            "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )
        cur.execute("ANALYZE place_embeddings")
    conn.commit()


def run(
    conn: psycopg.Connection[Any],
    kinds: set[str],
    limit: int | None,
    device: str | None = None,
    rebuild_index: bool = True,
) -> None:
    with etl_step(conn, "embed") as stats:
        if rebuild_index:
            drop_index(conn)
        stats.update(embed(conn, kinds, limit, device=device))
        build_index(conn)
