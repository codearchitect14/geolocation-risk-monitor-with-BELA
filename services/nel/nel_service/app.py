"""HTTP service around the BELA linker and the bge-m3 embedder.

Run: uvicorn nel_service.app:app --port 8082  (see services/nel/README.md for the environment variables).
Model calls are serialized on one worker thread because the GPU is a single resource. When more than
MAX_PENDING requests wait, new ones get 503 with a Retry-After header (backpressure).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psycopg
import torch
from fastapi import FastAPI, HTTPException, Request, Response
from huggingface_hub import hf_hub_download
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from nel_service.index import EntityIndex, qid_to_int
from nel_service.linker import Linker, Passage
from nel_service.model import ENCODER_NAME, ENCODER_REVISION
from nel_service.schemas import (
    CandidateOut,
    EmbedRequest,
    EmbedResponse,
    LinkRequest,
    LinkResponse,
    MentionOut,
    PassageOut,
)

log = logging.getLogger("nel.app")
ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = Path(os.environ.get("BELA_DIR", ROOT / "data" / "raw" / "models" / "bela"))
MAX_PENDING = int(os.environ.get("NEL_MAX_PENDING", "8"))
MICRO_BATCH = int(os.environ.get("NEL_MICRO_BATCH", "16"))
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")

REQUESTS = Counter("nel_requests_total", "Requests by endpoint and status", ["endpoint", "status"])
LATENCY = Histogram(
    "nel_request_seconds", "Request latency", ["endpoint"], buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30)
)
PASSAGES = Counter("nel_passages_total", "Passages linked")
MENTIONS = Counter("nel_mentions_total", "Mentions returned")
PENDING = Gauge("nel_pending_requests", "Requests waiting for the model")


def pick_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def load_place_qids(dsn: str) -> set[int]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT qid FROM places WHERE qid IS NOT NULL")
        return {qid_to_int(row[0]) for row in cur.fetchall()}


class State:
    linker: Linker | None = None
    embedder: Any = None
    device: torch.device
    executor = ThreadPoolExecutor(max_workers=1)
    pending = 0


state = State()


@asynccontextmanager
async def lifespan(_: FastAPI) -> Any:
    logging.basicConfig(level=logging.INFO)
    state.device = pick_device()
    dsn = os.environ.get("DATABASE_URL", "postgresql://meridian:meridian@localhost:5433/meridian").replace(
        "postgresql+psycopg://", "postgresql://"
    )
    started = time.perf_counter()
    place_qids = load_place_qids(dsn)
    index = EntityIndex(MODEL_DIR / "embeddings_fp16.npy", MODEL_DIR / "index.txt", place_qids, state.device)
    checkpoint = MODEL_DIR / os.environ.get("BELA_CHECKPOINT", "model_wiki.ckpt")
    sp_model = Path(hf_hub_download(ENCODER_NAME, "sentencepiece.bpe.model", revision=ENCODER_REVISION))
    state.linker = Linker(
        checkpoint, sp_model, index, state.device, md_threshold=float(os.environ.get("BELA_MD_THRESHOLD", "0.2"))
    )
    log.info(
        "linker ready on %s in %.0fs (checkpoint %s)", state.device, time.perf_counter() - started, checkpoint.name
    )
    yield
    state.executor.shutdown(wait=False)


app = FastAPI(title="Meridian NEL service", lifespan=lifespan)


async def run_on_model(endpoint: str, fn: Any, *args: Any) -> Any:
    if state.pending >= MAX_PENDING:
        REQUESTS.labels(endpoint, "503").inc()
        raise HTTPException(503, "model is busy", headers={"Retry-After": "2"})
    state.pending += 1
    PENDING.set(state.pending)
    started = time.perf_counter()
    try:
        value = await asyncio.get_running_loop().run_in_executor(state.executor, fn, *args)
        REQUESTS.labels(endpoint, "200").inc()
        return value
    except Exception:
        REQUESTS.labels(endpoint, "500").inc()
        raise
    finally:
        state.pending -= 1
        PENDING.set(state.pending)
        LATENCY.labels(endpoint).observe(time.perf_counter() - started)


@app.get("/health")
async def health() -> dict[str, Any]:
    ready = state.linker is not None
    if not ready:
        raise HTTPException(503, "loading")
    assert state.linker is not None
    return {
        "status": "ok",
        "device": str(state.device),
        "checkpoint": state.linker.checkpoint_name,
        "index_rows": state.linker.index.full.rows,
        "place_rows": state.linker.index.places.rows,
        "pending": state.pending,
    }


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _link(request: LinkRequest) -> LinkResponse:
    assert state.linker is not None
    started = time.perf_counter()
    ordered = sorted(range(len(request.passages)), key=lambda i: len(request.passages[i].text))
    results: dict[int, PassageOut] = {}
    for offset in range(0, len(ordered), MICRO_BATCH):
        batch_ids = ordered[offset : offset + MICRO_BATCH]
        passages = [
            Passage(request.passages[i].id, request.passages[i].text, request.passages[i].lang) for i in batch_ids
        ]
        for position, mentions in zip(batch_ids, state.linker.link(passages, request.top_k), strict=True):
            results[position] = PassageOut(
                id=request.passages[position].id,
                mentions=[
                    MentionOut(
                        start=m.start,
                        end=m.end,
                        surface=m.surface,
                        qid=m.qid,
                        md_score=m.md_score,
                        el_score=m.el_score,
                        candidates=[
                            CandidateOut(qid=c.qid, score=c.score, similarity=c.similarity) for c in m.candidates
                        ],
                        place_candidates=[
                            CandidateOut(qid=c.qid, score=c.score, similarity=c.similarity) for c in m.place_candidates
                        ],
                    )
                    for m in mentions
                ],
            )
    PASSAGES.inc(len(request.passages))
    MENTIONS.inc(sum(len(r.mentions) for r in results.values()))
    return LinkResponse(
        model=state.linker.checkpoint_name,
        results=[results[i] for i in range(len(request.passages))],
        seconds=time.perf_counter() - started,
    )


@app.post("/v1/link", response_model=LinkResponse)
async def link(request: LinkRequest) -> LinkResponse:
    return await run_on_model("link", _link, request)  # type: ignore[no-any-return]


def _embed(request: EmbedRequest) -> EmbedResponse:
    if state.embedder is None:
        from sentence_transformers import SentenceTransformer

        state.embedder = SentenceTransformer(EMBEDDING_MODEL, device=str(state.device))
        state.embedder.max_seq_length = 128
        if state.device.type != "cpu":
            state.embedder.half()
    vectors = state.embedder.encode(request.texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    return EmbedResponse(model=EMBEDDING_MODEL, dimensions=int(vectors.shape[1]), embeddings=vectors.tolist())


@app.post("/v1/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest, raw: Request) -> EmbedResponse:
    _ = raw
    return await run_on_model("embed", _embed, request)  # type: ignore[no-any-return]
