# Operations runbook

Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with local
authorities and follow their guidance.

This runbook covers day-to-day operation of the API, the worker, the database, and the processing services, and the procedures for
the failures we have planned for. Commands assume the repository root and the development layout (a local PostgreSQL 17 cluster on
port 5433, API on 8090, web on 3000). Production-style packaging is phase 11.

## Components and health

| Component | Start | Health | If it is down |
|---|---|---|---|
| PostgreSQL 17 (PostGIS, pgvector) | `make db-start` | `infra/postgres/dev_cluster.sh status`; API `GET /api/v1/health/ready` | API readiness fails (503); nothing is served. Restore service first, then check data. |
| API | `make api-up` | `GET /api/v1/health` (liveness), `/health/ready` (database) | Web app shows its error state; no data is lost. |
| Worker | `make api-worker` | process alive; log lines `meridian.worker` | Webhook retries, retention purge, audit verification and rollups pause. Alerts already created stay visible. |
| Valkey (optional) | `make valkey-up` | `valkey-cli ping` | Rate limits and event streams fall back to in-process memory (per instance). |
| Entity linker (NEL) | `make nel-up` | `GET :8082/health`; sources page | News is still processed with gazetteer rules; affected incidents are marked reduced confidence. |
| Language model server | `make llm-up` | `GET :8081/health`; sources page | News is classified by headline rules, place adjudication is skipped, incidents are marked reduced confidence. |
| Harvest scheduler | `make harvest-daemon` | `make harvest-status` | Feeds go stale; the sources page shows each feed job as ok, retrying, or failing. |

The sources page (Data sources in the application) shows the state of the feed jobs, of the model server and the entity linker, the
number of incidents built with a fallback in the last seven days, and the dead letter queue depth.

## Degraded modes

The news path never silently drops work because a dependency is down.

- **Model server down.** Headlines are labeled by conservative keyword rules (severity at most 2; a headline that may name a private
  person is not labeled). Model place adjudication is skipped. The incident is stored with `reduced_confidence = true`.
- **Entity linker down.** Places are found by matching capitalized strings against the gazetteer and re-ranked with context; the
  incident is marked reduced confidence. Calls to the linker are retried with backoff before this happens.
- **Neither can classify the headline.** The article's identifiers (never its text) go to `dead_letters` and are retried after 1
  minute, 5 minutes, 30 minutes, 2 hours and 12 hours, then abandoned. Retry with the caller that holds the article text:
  `meridian.events.news.retry_dead_letters(ingestor, text_for, now)`.
- **A hazard feed down.** The harvest job records each failure; after three consecutive failures the sources page shows `failing`.
  Events already stored are unaffected and their sources keep their last record time.
- **Webhook receiver down.** Deliveries are retried at 1 min, 5 min, 30 min, 2 h and 12 h, then abandoned; the delivery log shows each
  attempt. The alert itself is unaffected.

Inspect the queue:

```sql
SELECT status, count(*), min(next_attempt_at) FROM dead_letters GROUP BY status;
SELECT kind, ref, attempts, last_error FROM dead_letters WHERE status = 'abandoned' ORDER BY updated_at DESC LIMIT 20;
```

Requeue an abandoned item after the cause is fixed: `UPDATE dead_letters SET status = 'queued', attempts = 1, next_attempt_at = now() WHERE id = ...`.

## Backups

What to protect: the application database (tenants, users, assets, alerts, audit log, events) is the system of record. Place
embeddings (10 GB) and the place knowledge base are derived from `data/raw` and can be rebuilt (`make etl`, `make etl-embed`), so the
routine backup leaves out the embedding rows. Secrets (`.local/secrets` in development; `MS_SECRET_KEY` and `MS_JWT_PRIVATE_KEY` in
production) are stored in the secret manager, not in the database dump. Losing `MS_SECRET_KEY` makes stored MFA seeds and webhook
secrets unreadable.

Routine backup (custom format, compressed, restorable in parallel):

```bash
pg_dump --format=custom --compress=zstd:3 --no-owner --exclude-table-data=place_embeddings --file meridian-$(date -u +%Y%m%dT%H%M%SZ).dump meridian
```

Suggested policy for a production deployment: nightly dump retained 14 days, weekly retained 8 weeks, continuous WAL archiving for
point-in-time recovery with a target loss of at most 5 minutes, dumps copied to a second location and encrypted at rest. The
development cluster has no WAL archiving, so the recovery point there is the last dump.

## Restore

1. Stop the API and worker so nothing writes.
2. Create an empty database: `createdb meridian_restored`.
3. Restore: `pg_restore --dbname meridian_restored --jobs 4 --no-owner meridian-<stamp>.dump`. The dump creates the extensions
   (`postgis`, `vector`, `pg_trgm`, `pgcrypto`), which needs a role allowed to create them.
4. Re-grant the application roles if the cluster is new: `alembic upgrade head` is idempotent for roles (`meridian_app`,
   `meridian_platform`) and re-applies nothing when the version table is restored.
5. Verify: row counts of the main tables against the source, `SELECT * FROM audit_verify()` returns no bad id, and the readiness
   endpoint answers.
6. Point `DATABASE_URL` at the restored database and start the API and worker.
7. If embeddings were excluded, run `make etl-embed` (hours) or restore a full dump; name search keeps working without them, vector
   search for place linking needs them.

### Drill

`infra/ops/backup_drill.sh` performs steps 2 to 5 against a scratch database and prints a JSON summary (`FULL=1` includes the
embeddings). It never writes to the source database. Run it after every migration that changes the schema and at least monthly.
Results are recorded at the end of this page.

## Routine tasks

| Task | How |
|---|---|
| Apply migrations | `make db-upgrade` (alembic). Migrations are forward only in production; take a dump first. |
| Event lifecycle refresh | `make events-status` (also run by the worker) |
| Retention purge, audit chain verification | worker loop, or `python -m meridian.api.worker --once` |
| Rotate API keys / webhook secrets | Administration pages in the application |
| Rotate the token signing key | Replace `MS_JWT_PRIVATE_KEY`, restart the API. Users sign in again (refresh tokens are opaque and survive, access tokens do not). |
| Clear a login lockout | an administrator edits the user in the Administration page; limits are per address and per account and expire |
| Slow query review | `python infra/perf/slow_queries.py` after a load, see `docs/db_tuning.md` |
| Security scans | `make scans` (Bandit, pip-audit, npm audit, gitleaks, Trivy), `infra/ops/zap_baseline.sh` |

## Capacity notes

- The API holds a connection pool per process (`MS_DB_POOL_MIN`, `MS_DB_POOL_MAX`, default 2 and 24). Size `max_connections` for
  processes x pool max plus the worker and administrative sessions. A request waits up to `MS_DB_POOL_TIMEOUT_SECONDS` (8) for a
  free connection and then fails with a server error, which is the signal to add processes or raise the pool.
- Run more than one API process (for example `uvicorn --workers 4`) when the CPU of one process is saturated; see `docs/perf.md`
  for the measured capacity of a single process.
- Report generation (PDF, map images) runs inside the request in child processes; schedule large portfolio reports outside peak
  hours until they move to a queue.

## Incident checklist

1. Check the sources page and `GET /api/v1/health/ready`.
2. Check the API log (`.local/api.log` in development). Access log lines contain method, route template, status, time and request id
   only; look up a failing request by its id.
3. Database: `SELECT count(*) FROM pg_stat_activity` against `max_connections`; long queries in `pg_stat_activity` with
   `state = 'active'`.
4. If audit verification fails (`meridian.worker` logs `audit chain broken at entry N`), treat it as a security incident: stop
   writes, preserve the database, restore a known-good dump beside it, and compare from entry N.
5. If a tenant reports a wrong location, use the incident page's location panel (candidates and scores), then the corrections form.

## Drill results

| Date | Scope | Dump | Dump time | Restore time | Row counts | Extensions | Audit chain |
|---|---|---|---|---|---|---|---|
| 2026-11-04 | development database, embeddings excluded | 129 MB | 4.1 s | 11.2 s (4 jobs) | all ten compared tables equal (places 525,626; assets 122,865; audit log 524) | postgis, vector, pg_trgm restored | intact |

The drill covers the database. It does not cover a full machine loss: the secrets, the model checkpoints and the raw data
directory must come from their own sources (secret manager, `make llm-fetch`, the download scripts). A restore with the
embeddings (`FULL=1`) was not timed; it adds a 10 GB table and an HNSW index rebuild. Recovery point in development is the last dump
(no WAL archiving), so a recovery point objective for production depends on enabling archiving.
