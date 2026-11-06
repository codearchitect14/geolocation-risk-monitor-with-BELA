# Deployment: production-style container stack

Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with local
authorities and follow their guidance.

**Status.** The files in `infra/compose` and `infra/docker` were written and checked for structure (YAML parses, the Caddyfile
validates, the API requirements install and pass the API tests in a clean environment) but **have not been built or started**,
because Docker is not installed on the development machine. Build and test the stack before relying on it, and run
`trivy image` on each image (`docs/security.md` lists image scanning as open).

## What the stack runs

| Service | Image | Purpose | Limits (starting points) |
|---|---|---|---|
| caddy | `caddy:2-alpine` | TLS, HTTP/3, routing, access log with rotation | 1 CPU, 256 MB |
| web | built from `infra/docker/web.Dockerfile` | Next.js standalone server, non-root | 1 CPU, 768 MB |
| api | built from `infra/docker/api.Dockerfile` | FastAPI with two workers, non-root, read-only root file system | 2 CPU, 1.5 GB |
| worker | same image | webhook retries, purge, audit check, rollups | 1 CPU, 768 MB |
| migrate | same image | `alembic upgrade head`, runs once before the API starts | 1 CPU, 512 MB |
| postgres | built from `infra/postgres/Dockerfile` | PostgreSQL 17 with PostGIS and pgvector | 2 CPU, 4 GB |
| valkey | `valkey/valkey:8-alpine` | shared rate limits and event streams | 0.5 CPU, 192 MB |

Every service has `restart: unless-stopped` (the migration runs once), a health check where it has a port, JSON logs rotated at
10 MB times 5 files, `no-new-privileges`, and dropped capabilities (PostgreSQL keeps what its entrypoint needs; Caddy adds only
the right to bind low ports). PostgreSQL and Valkey are on an internal network with no route out and no published port. The API
and web are reachable only through Caddy.

The entity linking and language model services are **not** part of the stack; the news path degrades as described in
`docs/runbook.md` without them.

## First start

```bash
cp infra/compose/.env.prod.example infra/compose/.env.prod     # fill in every value; see the comments in the file
docker compose -f infra/compose/docker-compose.prod.yml --env-file infra/compose/.env.prod up -d --build
docker compose -f infra/compose/docker-compose.prod.yml --env-file infra/compose/.env.prod ps
```

The secrets are required: the API refuses to start in production without `MS_SECRET_KEY` and `MS_JWT_PRIVATE_KEY`, and compose
refuses to start without the database password and the site address. With `SITE_ADDRESS=localhost` Caddy issues a certificate from
its own authority, which browsers will not trust until its root is installed; use a real name for anything public.

Create the first accounts and load content:

```bash
docker compose -f infra/compose/docker-compose.prod.yml --env-file infra/compose/.env.prod exec api \
  python -m meridian.api.cli create-tenant --name "Example Company"
docker compose ... exec -e MS_NEW_PASSWORD='<password>' api python -m meridian.api.cli create-user \
  --email you@example.org --name "You" --role tenant_admin --tenant example-company
```

For a public demonstration, run `python -m meridian.demo seed` in the api container after the place knowledge base is loaded, set
`DEMO_MODE=1` and `DEMO_VIEWER=demo-viewer@example.com` in `.env.prod` so the login page shows the access box, and publish
only the viewer account.

## Places and data

The container stack does not build the place knowledge base. Restore it from a backup of a built database (`docs/runbook.md`,
"Restore") or run the ETL in a one-off container with the data directory mounted. The demonstration knowledge base
(`python -m meridian.etl build --demo`) needs only the small GeoNames and Natural Earth files.

## Operations

Backups, restore, degraded modes, and routine tasks are in `docs/runbook.md`. Logs: `docker compose logs -f api`, and the Caddy
access log in the `caddy_logs` volume. Resource limits are starting points; measure with the tools in `infra/perf` and adjust
(`docs/perf.md`).

## Known limits of this packaging

- The mail client speaks plain SMTP without login or STARTTLS; run a relay on the private network.
- The API image installs the native libraries for PDF reports but not the Chromium that turns report maps into PNG images
  (`playwright install chromium`). Without it the map is embedded as the SVG it is drawn from; the report still has its map.
- PostgreSQL runs as a single instance; replication and WAL archiving are not configured.
- No image has been scanned or signed, and no software bill of materials is generated.
