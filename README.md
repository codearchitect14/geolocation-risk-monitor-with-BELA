# Meridian Signal

Disruption intelligence for operations teams. The platform reads public news and public hazard feeds, finds where each
incident happened, scores how exposed a customer's sites and routes are, and raises alerts that people can acknowledge,
assign, and report on. Every location decision is shown with its evidence.

> Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with
> local authorities and follow their guidance.

## What is in this repository

| Area | Where | What it is |
|---|---|---|
| API and worker | `apps/api` | FastAPI service, PostgreSQL schema and migrations, event pipeline, exposure and alert logic |
| Web | `apps/web` | Next.js marketing site and the product application (map, incidents, alerts, assets, reports, administration, revenue) |
| Place knowledge base | `apps/api/meridian/etl` | GeoNames and Wikidata merged into one gazetteer with uncertainty radii |
| Entity linking | `services/nel`, `apps/api/meridian/linking` | BELA service, context re-ranker, optional local language model adjudication |
| Data | `data` | Acquisition scripts, manifest with checksums, gold sets, replay seed, licensing register |
| Operations | `infra` | PostgreSQL image, container stack, load and security tooling, backup drill |
| Documents | `docs` | Architecture, API guide, data guide, model card, evaluation, runbook, security, performance |

## Quick start: the demonstration

Needs Python 3.11 or newer, Node.js 20 or newer, curl, and PostgreSQL 17 with PostGIS and pgvector
(`brew install postgresql@17 postgis pgvector` on macOS; set `PGBIN` if the binaries are elsewhere).

```bash
git clone https://github.com/codearchitect14/geolocation-risk-monitor-with-BELA.git
cd geolocation-risk-monitor-with-BELA
make demo
```

`make demo` installs the dependencies, downloads the small data files (GeoNames cities and Natural Earth boundaries, checksum
verified), creates a local PostgreSQL cluster, builds a small place knowledge base, loads a recorded earthquake feed as history,
creates a demonstration tenant with accounts and illustrative assets, and starts the API and the web application. Sign-in details
for six accounts are printed once at the end; only their hashes are stored. Open `http://127.0.0.1:3000/login`.

```bash
make replay        # play the recorded feed live: new incidents appear on the map and alerts are raised
make demo-down     # stop the servers (the data stays)
make demo-reset    # delete the demo database
```

The public demonstration uses the read-only viewer account (`demo-viewer@example.com`). Administrator and platform accounts ask for
an authenticator app at first sign-in. Everything shown is synthetic or illustrative: the sites, the portfolio, and the
revenue history. Incidents come from a recorded public earthquake feed that is re-timed for the demonstration.

What the demonstration does not include: the entity linking model (about 33 GB), the local language model, and the full place
knowledge base (Wikidata subset, embeddings). News articles are therefore not processed in the demonstration; see
`docs/data-guide.md` to build the full set, and `docs/architecture.md` for how the pieces fit.

## Development

```bash
make setup              # Python environment
make db-init db-start   # local PostgreSQL cluster (.local/pgdata)
make db-upgrade         # migrations
make api-up             # API on 127.0.0.1:8090
make web-dev            # web on localhost:3000
make check              # lint, types, tests, character check
make web-check          # web lint, types, format, unit tests
make web-e2e            # end-to-end tests (needs the API, the web server, and seeded test accounts)
```

The test suites are `pytest` (about 450 tests; they create a throwaway database) and Playwright (68 tests in Chromium; the
cross-browser run is `make web-cross`). Style rules: professional neutral text, no U+2014 character (`infra/ci/check_no_em_dash.py`).

## Documents

- `docs/architecture.md`: components, data flow, tenancy and security boundaries
- `docs/api-guide.md`: authentication, endpoints, and samples in curl, Python, and JavaScript; `docs/openapi.json` is the reference
- `docs/data-guide.md`: sources, how each is acquired, the place knowledge base, and how to rebuild
- `docs/model_card.md` and `docs/eval/report.md`: what the linking engine does, how it was evaluated, and where it is weak
- `docs/runbook.md`: operations, degraded modes, backup and restore
- `docs/security.md`: controls, test evidence, scan results, and open items
- `docs/perf.md` and `docs/db_tuning.md`: load results and database tuning
- `docs/deploy.md`: the production-style container stack
- `docs/licensing.md`: data and software licenses
- `docs/walkthrough.md`: a scripted tour of the product
- `docs/adr`: architecture decision records

## Status and limits

Built in phases against `PLAN_disruption_intelligence.md`. Open items are listed in the last section of each document, in
particular `docs/security.md` (CSP `unsafe-inline`, active scan, image scan), `docs/perf.md` (browser frame rate not measured),
and `docs/web.md` (known gaps in the application). The container stack has not been built or run on the development machine.
