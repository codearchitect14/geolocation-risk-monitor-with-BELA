# NEL service

HTTP service around the BELA entity linker (MIT, Meta) and the bge-m3 embedder. It runs on the Apple GPU (MPS)
and falls back to CUDA or CPU.

## Files

The model files come from the Hugging Face repository `wannaphong/BELA` (a mirror of the official release):

| File | Size | Purpose |
|---|---|---|
| `model_wiki.ckpt` | 2.2 GB | Context encoder, mention detector, and link classifier trained on Wikipedia (default) |
| `model_e2e.ckpt` | 2.2 GB | Variant that also tags general concepts; kept for the evaluation |
| `index.txt` | 158 MB | QID of every entity, one per line (16.5 million) |
| `embeddings.pt` | 19.8 GB | 300 dimensional entity vectors, one per line of `index.txt` |

```
.venv/bin/python data/scripts/parallel_download.py wannaphong/BELA embeddings.pt data/raw/models/bela/embeddings.pt \
    --sha256 c2e38b13703cea69c2c12fe14eba29f00c98e74bd16fd2e01bb29183aac5a309
.venv/bin/python services/nel/prepare_index.py       # float16 copy, 9.9 GB, once
```

Checkpoints are read with `torch.load(weights_only=True)`, so no pickled code is executed.

## Running

```
cd services/nel && ../../.venv/bin/uvicorn nel_service.app:app --host 127.0.0.1 --port 8082
```

| Variable | Default | Meaning |
|---|---|---|
| `BELA_CHECKPOINT` | `model_wiki.ckpt` | Which checkpoint to load |
| `BELA_MD_THRESHOLD` | `0.2` | Mention detection threshold |
| `NEL_MAX_PENDING` | `8` | Requests waiting for the model before new ones get 503 |
| `NEL_MICRO_BATCH` | `16` | Passages per model call |
| `DATABASE_URL` | local cluster | Used once at start to list the QIDs that are known places |

Start-up takes about a minute (9.9 GB of vectors moved to the GPU). Memory: about 11 GB on the device.

## API

`POST /v1/link` with `{"passages": [{"id", "text", "lang"}], "top_k": 10}` returns for each passage the mentions
(`start`, `end`, `surface`, `qid`, `md_score`, `el_score`) with `candidates` (BELA's own top candidates) and
`place_candidates` (the best candidates among known places), each as `{qid, score, similarity}`.
`POST /v1/embed` returns bge-m3 vectors. `GET /health` and `GET /metrics` (Prometheus).
