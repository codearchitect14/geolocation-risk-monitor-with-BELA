# ADR-009: Backend API, authentication, and tenant isolation

- Status: accepted
- Date: 2026-11-02

## Context

Phase 5 exposes the pipeline to customers. The main risks are cross-tenant disclosure of asset locations, account takeover,
and abuse of outbound features (webhooks, the place linker). The specification asks for server-side enforcement and Row Level
Security, not for hiding actions in the interface.

## Decisions

- **Tenant isolation in the database, with a restricted role.** The application connects as the migration owner but every tenant
  request first runs `SET LOCAL ROLE meridian_app` and sets `app.tenant_id`, `app.user_id`, `app.role`, and `app.bypass` with
  `set_config(..., true)`. The role has no `BYPASSRLS`; policies compare `tenant_id` with `app_tenant()`. A commit ends the
  transaction and the `SET LOCAL` values with it, so `Tx.commit` and `Tx.rollback` apply the context again before returning. With
  no context, policies match no rows. Place, event, and source tables are readable and not writable for the role. Password hashes,
  refresh tokens, MFA seeds, and reset tokens have no grants at all for the role (users has column level grants).
- **Authentication code uses the owner connection.** Credentials must be read before a tenant is known. That code is small, lives
  in `routers/auth.py` and `services/`, and is covered by tests that attack it directly.
- **Sessions.** A 15 minute EdDSA access token in an `HttpOnly; Secure; SameSite=Strict` cookie, an opaque refresh token (stored as a
  SHA-256 hash) rotated on every use, a session family per login, reuse detection that revokes the family, idle and absolute
  lifetimes, and a double-submit CSRF value for cookie sessions. API keys use a different header and are not subject to CSRF.
  The role is read from the database on every request, so role changes and disabling take effect at once.
- **MFA.** TOTP with single-use codes (a replay cache), ten hashed recovery codes, seeds encrypted at rest. Tenant and platform
  administrators cannot obtain a session without it: login returns an enrollment token instead.
- **Lockout without enumeration.** Wrong password, unknown account, locked, and disabled accounts return the same response; a
  dummy hash is verified when the account does not exist. Five failures lock the account for an exponentially growing time.
  Per-address and per-account rate limits apply on top.
- **Audit log in the database.** A trigger takes an advisory lock, assigns the id, links `prev_hash`, and computes `entry_hash` over
  all fields. Update, delete, and truncate raise. `audit_verify()` walks the chain. Audit details pass through a sanitizer that removes
  passwords, tokens, keys, and coordinates.
- **Webhooks.** HTTPS only, every resolved address must be public, delivery connects to the validated address with the original
  host as SNI (no second DNS lookup), no redirects, HMAC signature with timestamp, a seven day overlap when the secret rotates, and
  retries with backoff. Payloads carry the asset name and distance; coordinates need both the tenant setting and the webhook flag.
- **Rate limits and streams use Valkey when reachable,** and an in-process fallback otherwise. Alert streams are scoped by channel
  name to the tenant and capped per tenant.
- **Jobs without a task queue.** Webhook delivery, retention purge, and audit verification are plain functions run by
  `python -m meridian.api.worker`; they can be wrapped as Celery tasks without change. This avoids a broker dependency for a first
  deployment.

## Consequences

- Any new tenant table needs a policy in a migration; the structural tests list the tables and will fail if a new table with a
  `tenant_id` column is readable across tenants.
- The owner connection is trusted in authentication code and background jobs. A defect there is not contained by Row Level Security.
- Platform administrators read across tenants and act inside one with `X-Tenant-Id`, which switches them to that tenant's policies.
