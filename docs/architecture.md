# Architecture overview

Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with local
authorities and follow their guidance.

## Components

```
 public feeds                                                        customers
 (USGS, NWS, FIRMS,                                                  (browser, API, webhooks, email)
  ReliefWeb, GDELT,                                                         ^
  news pages)                                                               |
      |                                                                     |
      v                                                              +------+-------+
 harvest scheduler  --->  data/raw (files)                           |    Caddy     |  TLS, routing (container stack)
 (data/scripts)                 |                                    +------+-------+
                                v                                           |
        +-----------------------------------------+          +--------------+--------------+
        | event pipeline  (apps/api/meridian/events)|         |  web (Next.js)   API (FastAPI) |
        |  normalize -> cluster -> status         |          +--------------+--------------+
        |  news: classify -> link places -> locate |                         |
        +----------------+------------------------+                          |
                         |                                                   |
         +---------------+---------------+                                   |
         v                               v                                   v
  entity linking service         language model server                 PostgreSQL 17
  (services/nel, BELA, 8082)     (llama.cpp, 8081, optional)           PostGIS, pgvector, RLS
                                                                              ^
                                        worker (webhooks, purge, audit check) +   Valkey (optional: rate limits, streams)
```

| Component | Responsibility | Where |
|---|---|---|
| Harvest | Pull public feeds on intervals; write files and a heartbeat per job | `data/scripts/scheduler.py` |
| Place knowledge base | One gazetteer (GeoNames merged with Wikidata) with types, hierarchy, and an uncertainty radius per place | `apps/api/meridian/etl` |
| Linking engine | Find place mentions, link them, choose the event location with a confidence | `services/nel`, `apps/api/meridian/linking` |
| Event pipeline | Normalize each source to one shape, cluster reports of the same incident, keep the lifecycle (new, developing, ongoing, resolved) | `apps/api/meridian/events` |
| Exposure and alerts | Score each tenant asset against each incident; create, update, and suppress alerts | `events/exposure.py`, `events/alerts.py` |
| API | Authentication, roles, tenant data, workflows, reports, administration, revenue analytics | `apps/api/meridian/api` |
| Worker | Webhook retries, retention purge, audit chain verification, rollups | `apps/api/meridian/api/worker.py` |
| Web | Marketing site and the product application | `apps/web` |

## Data flow

1. **Hazard feeds** (USGS, NWS, FIRMS, ReliefWeb) arrive as structured records with coordinates. A normalizer turns each into a
   common event shape.
2. **News** arrives as an article. A language model labels the headline (type, subtype, severity, and whether it names a private
   person); the linking engine finds and links places; rules choose one event location. If the model server or the linker is down,
   headline rules and gazetteer matching take over and the incident is marked reduced confidence; articles that cannot be
   labeled wait in a dead letter queue (`docs/runbook.md`).
3. **Clustering.** A new record joins an existing incident when it is the same type, close enough in space (scaled by the location
   uncertainty), and close in time; two news reports also need similar titles. The incident then has several sources and a
   confirmation state.
4. **Exposure.** For each incident the database finds active assets within a search radius (PostGIS geography, index served)
   and scores each: type weight, severity, proximity, location confidence, source reliability, recency decay, and asset
   criticality. Every component is stored with the score.
5. **Alerts.** A score at or above the tenant's threshold creates an alert; a higher level or score updates it; maintenance
   windows suppress it. The alert is delivered by the live stream, the webhook, and email (without coordinates unless the tenant
   opts in). People acknowledge, assign, escalate, or dismiss it with a reason, and every step is recorded.

## Tenancy and security boundaries

- Every tenant table has Row Level Security. Tenant requests run as database role `meridian_app` with the tenant set for the
  transaction; platform staff run as `meridian_platform`. Events, places, and sources are global and read only for tenants.
- Authentication: EdDSA access tokens in httpOnly cookies, rotating refresh tokens, CSRF double submit, TOTP for administrators,
  scoped API keys. Roles: viewer, analyst, manager, tenant administrator; platform administrator and finance analyst have no tenant.
- Asset coordinates are confidential: absent from logs, notifications by default, and third party services (maps are rendered
  from self-hosted data).
- Article and report text is untrusted. It is delimited for the language model, whose output is schema constrained and validated,
  and rendered as text. The model never decides an alert on its own: it labels and arbitrates between candidate places, and the
  exposure rules decide.
- Audit log is append only and hash chained; the worker verifies the chain.

Controls and test evidence: `docs/security.md`. Design reasons: `docs/adr`.

## Runtime shape

| Process | Port (development) | Notes |
|---|---|---|
| web | 3000 | proxies `/api` to the API |
| API | 8090 | stateless; scales by processes; connection pool per process |
| worker | none | one instance |
| PostgreSQL | 5433 | the system of record |
| entity linker | 8082 | optional; GPU or CPU; about 33 GB of model files |
| language model server | 8081 | optional |
| Valkey | 6379 | optional; without it, limits and streams are per process |

The container stack (`docs/deploy.md`) runs web, API, worker, migrations, PostgreSQL, Valkey, and Caddy. The two model services
are not part of it.
