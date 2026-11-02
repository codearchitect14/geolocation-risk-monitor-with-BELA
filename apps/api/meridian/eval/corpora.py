"""Load the public geoparsing corpora and map their gold annotations to knowledge-base places."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from meridian.config import get_settings
from meridian.eval.metrics import Gold
from meridian.geo.names import normalize_name

EUPEG_CORPORA = ("lgl", "geovirus", "tr-news", "geowebnews", "wiktor")
WIKTOR_SAMPLE = 400  # WikToR has 5,000 synthetic pages; a seeded sample keeps the corpora balanced


@dataclass
class Document:
    corpus: str
    doc_id: str
    text: str
    gold: list[Gold]
    split: str  # dev or test


def split_of(corpus: str, doc_id: str) -> str:
    """Deterministic 50/50 split by document."""
    digest = hashlib.sha256(f"geo-split-42:{corpus}:{doc_id}".encode()).digest()
    return "dev" if digest[0] % 2 == 0 else "test"


def read_documents(corpora: tuple[str, ...] = EUPEG_CORPORA, root: Path | None = None) -> Iterator[dict[str, Any]]:
    base = root or get_settings().data_dir / "raw" / "eval" / "eupeg"
    for corpus in corpora:
        path = base / f"{corpus}.jsonl"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                doc = json.loads(line)
                if corpus == "wiktor" and index % (5000 // WIKTOR_SAMPLE) != 0:
                    continue
                yield doc


def resolve_gold_places(conn: psycopg.Connection[Any], docs: list[dict[str, Any]]) -> dict[int, int]:
    """GeoNames id to place id for every gold identifier present in the knowledge base."""
    ids = sorted(
        {
            int(t["geonames_id"])
            for d in docs
            for t in d["toponyms"]
            if t.get("geonames_id") and str(t["geonames_id"]).isdigit()
        }
    )
    if not ids:
        return {}
    with conn.cursor() as cur:
        cur.execute("SELECT geonames_id, id FROM places WHERE geonames_id = ANY(%s)", (ids,))
        return {int(g): int(p) for g, p in cur.fetchall()}


def load_documents(conn: psycopg.Connection[Any], corpora: tuple[str, ...] = EUPEG_CORPORA) -> list[Document]:
    raw = list(read_documents(corpora))
    mapping = resolve_gold_places(conn, raw)
    documents = []
    for doc in raw:
        gold = []
        for t in doc["toponyms"]:
            if t.get("lat") is None or t.get("lon") is None or not t.get("offset_ok", True):
                continue
            if t["lat"] == 0 and t["lon"] == 0:
                continue
            gid = t.get("geonames_id")
            gold.append(
                Gold(
                    str(doc["doc_id"]),
                    doc["corpus"],
                    t["start"],
                    t["end"],
                    t["surface"],
                    t["lat"],
                    t["lon"],
                    mapping.get(int(gid)) if gid and str(gid).isdigit() else None,
                )
            )
        if gold and doc["text"]:
            documents.append(
                Document(
                    doc["corpus"], str(doc["doc_id"]), doc["text"], gold, split_of(doc["corpus"], str(doc["doc_id"]))
                )
            )
    return documents


def normalized_surface(gold: Gold) -> str:
    return normalize_name(gold.surface)
