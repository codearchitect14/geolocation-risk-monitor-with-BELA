# ADR-004: PostgreSQL 17 with PostGIS and pgvector

- Status: accepted
- Date: 2026-10-30

## Context

The plan names PostgreSQL 16. The Homebrew bottles for PostGIS 3.6 and pgvector 0.8 are
built for PostgreSQL 17 and 18 only, so a native development cluster on PostgreSQL 16 would
require building both extensions from source. The Docker route in the plan is not available
on the development machine.

## Decision

Use PostgreSQL 17 for development and for the container image (`infra/postgres/Dockerfile`
uses the PostGIS image for version 17). Nothing in the schema depends on a version specific
feature other than `UNIQUE NULLS NOT DISTINCT` (PostgreSQL 15 or later), so PostgreSQL 16 stays
a compatible deployment target.

The development cluster is created by `infra/postgres/dev_cluster.sh init` in `.local/pgdata`
(git-ignored) on port 5433, listening on localhost only, with a development-only role.

## Consequences

- The Docker image has not been built on the development machine. Build and test it before
  relying on it.
- Production credentials must never reuse the development role and password.
- Extension versions in use: PostGIS 3.6.4, pgvector 0.8.7.

## Latency targets

p95 latency targets for the core queries on the development database. They are checked by
`make etl-plans`, which writes the measured values and `EXPLAIN` output to `docs/query_plans.md`.

| Query | p95 target (ms) |
|---|---:|
| Radius search, 50 km (geography expression index) | 50 |
| Five nearest places (KNN on the geometry index) | 20 |
| Admin-1 polygon containing a point | 30 |
| Places inside an admin-1 polygon | 100 |
| Exact normalized name | 10 |
| Trigram name search | 100 |
| H3 cell and first ring | 30 |
| Vector nearest neighbors (HNSW) | 50 |

## Bulk loading embeddings

Drop the HNSW index before a bulk load and rebuild it afterwards. With the index in place each
insert costs 5 to 8 ms (about 160 rows per second); without it the job runs at about 1,300 rows
per second. The embedding job does this automatically. Building the index for 756,000 vectors took
about 20 minutes with 2 GB of `maintenance_work_mem`.
