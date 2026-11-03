# ADR-011: Revenue metrics in SQL, and analytics serving

- Status: accepted
- Date: 2026-11-03

## Context

Phase 7 adds 36 months of synthetic business history, metric definitions, a forecast, and operational analytics. Finance data must
stay out of reach of tenant roles, numbers must agree wherever they appear, and the endpoints must stay quick on the seeded data.

## Decisions

- **Definitions live in SQL.** MRR, movements, retention, cohorts, and unit economics are materialized views and views created by one
  migration, described in `docs/metrics.md`. The API reads them and never recomputes a definition in Python. The exception is the
  filtered series, which sum the same tenant level view with a `WHERE` clause.
- **Movements are derived, not stored.** Each tenant's MRR is compared with the previous month end. Because the classification is
  exhaustive, the sum of movements equals the change in MRR by construction, and a test checks it for every month, against an
  independent calculation from the CSV files, and for a region slice.
- **Views are gated like tables.** Materialized views cannot have Row Level Security and the app role has no grant on them. The role
  reads wrapper views (`*_v`) that return rows only when `app_role()` is finance_analyst or platform_admin. A tenant role that reaches
  the SQL by mistake gets zero rows; a test covers every view.
- **One daily statistics shape for tenant and platform.** `ops_stats_daily` is written by a nightly rollup (live tenants) and by the demo
  loader (synthetic tenants). A query prefers a statistics row and falls back to the alert tables for a tenant and date without one, so today is
  never empty and nothing is counted twice. Tenant endpoints get Row Level Security for free; the platform endpoints return counts only.
- **Caching in the process, keyed by scope.** A 60 second cache keyed by scope, parameters, and the metric refresh time, plus ETags. A tenant
  id is part of every tenant key, and a platform administrator who scopes into a tenant gets a different key. A shared cache (Valkey) is the
  next step when several API processes run.
- **The forecast is an estimate.** Damped additive trend exponential smoothing with an 80 percent interval, labeled in the response. It was
  chosen for stability on 36 monthly points. It needs 18 months of history and refuses otherwise.
- **Synthetic data is deterministic and calibrated.** `random.Random(42)` only; two runs give identical files. The ending ARR lands at about
  6.9 million USD, inside the specified 5 to 9 million envelope. Tenant names are invented word combinations.

## Consequences

- Changing a definition is a migration; the views are refreshed with `refresh_metrics()`.
- Metrics are as fresh as the last refresh (nightly or manual); the response says when that was (`as_of`).
- With a plan filter, movements do not reconcile (a documented consequence of classifying by current attributes).
- Pandas and statsmodels are imported when the API starts (about a second), so the first forecast request is not slow.
