# ADR-014: Hardening, performance, and resilience

Status: accepted (phase 10)

## Context

Phase 10 asks for a security review with scans, load tests with recorded latency, database tuning, graceful degradation when the
model server, the entity linker, or a feed is down, a backup drill, and a cross-browser pass. Several findings changed the design.

## Decisions

1. **Connection pool.** The API opens connections through a process wide `psycopg_pool` pool instead of one connection per use.
   Every authenticated request previously opened two connections. A connection is rolled back before it returns to the pool, so
   `SET LOCAL ROLE` and the tenant context never carry over. Sizing is configurable (`MS_DB_POOL_MIN`, `MS_DB_POOL_MAX`,
   `MS_DB_POOL_TIMEOUT_SECONDS`).
2. **Row Level Security that an index can serve.** The tenant policy `tenant_id = app_tenant() OR app_bypass()` forced sequential
   scans of whole tables. Platform staff now run under a second role, `meridian_platform`, a member of `meridian_app` with explicit
   allow-all policies on the tenant tables, and the tenant policy is the plain equality. Isolation is unchanged for tenant roles
   and is covered by the existing RLS, tenancy, and role matrix tests. The role is created by migration 0012 and is not dropped on
   downgrade, because roles are cluster wide.
3. **Degrade, mark, and queue instead of dropping.** When the model server is down the news path labels headlines with
   conservative rules and skips model adjudication. When the entity linker is down it uses gazetteer matching with context
   re-ranking. Events built either way carry `reduced_confidence`. Articles that cannot be labeled go to a dead letter queue with
   growing delays (1 minute to 12 hours, six attempts), then are abandoned and stay visible. The queue holds identifiers only, never
   article text, which keeps the rule that full article text is not stored.
4. **Rules are deliberately weak.** The headline rules cap severity at 2 and refuse any headline that looks like it names a private
   person. A missed label goes to the queue, which is preferred to a confident wrong label.
5. **Visible status.** The sources page shows the state of each feed job (from the status file every harvest job writes), the model
   server and entity linker, the number of reduced confidence incidents in the last seven days, and the queue depth.
6. **Scans without Docker.** Docker is not installed on the development machine. Bandit, pip-audit, npm audit, gitleaks, Trivy
   (filesystem and configuration), and the OWASP ZAP automation framework (a local install) were run directly; image scanning needs
   a built image and is left to the packaging phase.
7. **Dependencies.** The production dependency tree has no known vulnerabilities: Next.js is held on 15.5 with PostCSS forced to the
   patched release through an `overrides` entry, and ECharts moved to 6.1 for a cross-site scripting fix. Findings that remain are
   in development tooling only (see `docs/security.md`).

## Consequences

- One API process sustains about 430 requests per second of the mixed map and dashboard workload with a 150 ms p95 and no think time
  (`docs/perf.md`), roughly twice the capacity before the changes.
- Platform requests no longer set `app.bypass` to select a different policy but to select a different role; code that opens a
  transaction for a platform user must go through `db.open_tx` (it does).
- A request that cannot get a pooled connection within eight seconds fails; the runbook describes sizing.
- The weaker fallbacks lower precision. The evaluation does not cover them; `docs/perf.md` records only that they run.
