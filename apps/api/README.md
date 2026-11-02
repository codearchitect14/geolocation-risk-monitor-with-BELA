# API package: database, place knowledge base

This package holds the database schema (Alembic migrations) and the ETL that builds the place
knowledge base. The HTTP application is added in a later phase.

## Local database

PostgreSQL 17 with PostGIS and pgvector, see `docs/adr/ADR-004-postgresql-17-for-development.md`.

```
brew install postgresql@17 postgis pgvector      # once
make db-init                                      # creates .local/pgdata on port 5433
make db-upgrade                                   # applies migrations/versions
```

Connection settings come from `DATABASE_URL` (see `.env.example`). The default points at the
development cluster. `infra/postgres/dev_cluster.sh psql` opens a shell.

## Schema

Migrations live in `migrations/versions` and execute the SQL in `migrations/sql`:

| Revision | Content |
|---|---|
| 0001 | Extensions: postgis, vector, pg_trgm, pgcrypto |
| 0002 | Reference tables, uncertainty rules, `places`, `place_aliases`, `place_embeddings`, review and ETL tables |
| 0003 | Tenancy and security, news and NLP, events, assets and alerts, business tables |

Row level security and the materialized views `mrr_monthly` and `cohort_retention` are added in
phases 5 and 7, with the code that depends on them.

## Building the place knowledge base

Inputs are produced by phase 1 (`make data`, `make data-wikidata`).

```
make etl            # reference data, staging, merge, hierarchy, uncertainty, polygons, H3
make etl-embed      # bge-m3 embeddings, most populous places first (EMBED_LIMIT=100000 to bound)
make etl-quality    # quality checks, 1,000 name search evaluation, docs/place_kb_report.md
make etl-plans      # latency and EXPLAIN output, docs/query_plans.md
```

Steps can also be run one at a time: `python -m meridian.etl reference|stage-geonames|stage-wikidata|merge|hierarchy|finalize|embed|quality|eval|plans`
from this directory with `PYTHONPATH=.`.

Design decisions are in `docs/adr/ADR-005-place-knowledge-base.md`. Results of the last build are
in `docs/place_kb_report.md`.

## Using the gazetteer

```python
from meridian.db import connect
from meridian.geo.search import search_places

with connect() as conn:
    for hit in search_places(conn, "Springfield", k=5, country_code="US"):
        print(hit.name, hit.type, hit.country_code, hit.uncertainty_km, round(hit.score, 3))
```

`meridian.geo.names.normalize_name` produces the comparison key stored in the database; apply it to
any text before comparing it with `name_normalized` or `alias_normalized`.

## Tests

```
.venv/bin/pytest apps/api
```

Database tests create a throwaway database on the local cluster and drop it afterwards; they are
skipped when PostgreSQL is not reachable.

## Place linking engine (phase 3)

```
make nel-index                 # one-time: float16 copy of the BELA entity vectors (services/nel/README.md)
make nel-up && make llm-up     # entity linker (port 8082) and local language model (port 8081), both on the Apple GPU
make geo-up                    # HTTP service for POST /v1/locate and the gazetteer search (port 8083)
make eval-cache eval-train eval   # BELA over the public corpora, train the re-ranker, evaluate, write docs/eval/report.md
make eval-throughput           # 10,000 article run
make eval-gkg                  # agreement with GDELT's own locations
```

Library entry point: `meridian.linking.locate.locate(pipeline, text, title=..., outlet_country=...)`. Configuration is versioned in
`meridian/config/geo_config_v1.yaml`. Results: `docs/eval/report.md`; limits and failure modes: `docs/model_card.md`.

`python -m meridian.etl enrich --nel-cache <file>` adds places that BELA proposes but the place table lacks, through the Wikidata API
(set `MS_CONTACT` to a URL or email: Wikimedia rejects anonymous clients). A full dump pass (`make data-wikidata`) makes this unnecessary.

## Event pipeline and exposure (phase 4)

```
make events-demo               # synthetic tenant (150 sites sampled from the place table), labeled illustrative
make events-usgs               # USGS files in data/raw/hazards/usgs (REPLAY=1 scores each record as of its own time)
make events-nws                # NWS alerts; zone polygons are fetched once and cached (set MS_CONTACT)
make events-status             # refresh new/developing/ongoing/resolved
make events-smoke              # classifier smoke check on 37 author-written headlines (not a gold evaluation)
make events-synth              # exposure alert precision and recall on synthetic scenarios
make events-report             # counts of events, exposures, and alerts
python -m meridian.events replay-news --path <cc_news parquet> --limit 150   # testing use only
```

Rules and weights are in `meridian/config/events_config_v1.yaml`; every event, exposure, and alert row records the version. Modules in
`meridian/events`: `normalizers/` (usgs, nws, firms, reliefweb), `classify.py` (local model label), `news.py` (article to event),
`ingest.py` (create, revise, supersede, merge), `status.py`, `exposure.py`, `alerts.py`, `service.py` (feed files), `cli.py`.
Design and limits: `docs/adr/ADR-008-event-pipeline.md` and `docs/events_report.md`.
