# Security controls and test evidence (phase 5)

Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with local
authorities and follow their guidance.

This page maps the security specification to what is implemented and where it is tested. Design reasons are in
`docs/adr/ADR-009-api-security.md`. The API description is `docs/openapi.json` (also served at `/api/docs` outside production).

## Controls

| Requirement | Implementation | Tests |
|---|---|---|
| Argon2id passwords, 12+ characters, strength check, common password rejection | `security/passwords.py`: time 3, 64 MiB, 2 lanes (about 45 ms on the development machine); zxcvbn score of 3 or more with the user's own email and name as inputs | `test_password_policy`, reset tests |
| Login protection | per address and per account limits, generic errors, lockout with growing duration, audit entries for failures | `test_lockout...`, `test_login_rate_limits...`, `test_wrong_password_and_unknown_account...` |
| MFA with TOTP and recovery codes, mandatory for administrators | `routers/auth.py`, `security/mfa.py`; enrollment token flow; seeds encrypted | `test_administrators_must_use_mfa`, `test_totp_codes_are_single_use...` |
| Short-lived EdDSA access token in an httpOnly Secure SameSite=Strict cookie | `security/tokens.py`, `services/sessions.py` | `test_login_sets_hardened_cookies`, `test_expired_and_forged_access_tokens...` |
| Rotating opaque refresh tokens with reuse detection | `services/sessions.rotate` | `test_refresh_rotates_and_reuse_revokes_the_family`, `test_session_lifetimes...` |
| CSRF double submit | `auth._principal_from_cookie`, `auth/refresh`, `auth/logout` | `test_csrf_is_required_for_cookie_sessions_only` |
| Password reset without enumeration | single-use hashed 30 minute tokens, identical responses, sessions revoked on reset | `test_password_reset_flow`, `test_reset_tokens_expire` |
| API keys: prefix and secret, hashed, scoped, expiring, last used | `services/apikeys.py` | `test_api_key_lifecycle`, `test_api_key_rate_limit` |
| RBAC with server side checks | `permissions.py`, `auth.require`; table from section 10 | `test_role_against_every_endpoint` (6 roles x 56 requests), `test_every_route_requires_authentication...` |
| Row Level Security, per request tenant setting | migration `0006`, `db.Tx` | `test_api_rls.py` (9 tests), `test_api_tenancy.py` (10 tests) including spatial queries and GeoJSON endpoints |
| Append-only hash chained audit log | database trigger and `audit_verify()` | `test_audit_log_is_append_only_and_chained`, `test_audit_tampering_is_detected` |
| Rate limits per address, user, and key | `middleware.py`, `auth.py`, `security/ratelimit.py` (Valkey or memory) | `test_user_and_ip_rate_limits`, `test_valkey_rate_limiter_is_shared_between_instances` |
| Request size limits, strict validation | middleware byte counter, Pydantic models with bounds | `test_oversized_bodies_are_rejected`, validation cases throughout |
| Idempotency keys for uploads | `routers/assets.upload_assets` | `test_upload_idempotency` |
| Upload safety | size, row, and vertex limits, coordinate ranges, geometry validity, text and content checks, control character removal | `test_upload_limits_and_content_checks`, `test_geojson_upload...` |
| Formula injection protection on exports | `services/uploads.csv_safe` on asset exports and portfolio CSV | `test_exports_neutralize_spreadsheet_formulas`, `test_reports_escape_content...` |
| Server-sent events scoped by tenant | `routers/system.py`, `notify.py`, channels named by tenant | `test_streams_deliver_only_the_tenants_own_messages`, `test_valkey_pubsub_delivers_across_publishers` |
| Webhooks: HMAC, retries, SSRF protection, delivery log | `services/webhooks.py`, `security/ssrf.py` | `test_api_webhooks.py` (14 tests), SSRF address matrix (14 addresses) |
| Security headers, no CORS | `middleware.py` | `test_security_headers_on_every_response`, `test_cors_is_not_enabled` |
| Logs without credentials or asset coordinates | access log records method, route template, status, time, request id only; audit sanitizer | `test_audit_entries_never_hold_secrets_or_coordinates` |
| Asset coordinates absent from notifications by default | `notify.alert_payload` | `test_payload_contains_no_coordinates_unless_both_opt_in` |
| Briefing text validated against stored fields | `services/briefings.validate_narrative` | `test_briefing_narratives_are_validated_against_the_evidence` |
| Retention purge | `worker.purge`, per tenant `retention_days` | `test_purge_respects_retention...` |
| Corrections process | `/corrections`, platform review queue | `test_corrections_and_review` |

## Scans run in the development environment

| Scan | Result |
|---|---|
| Bandit on `meridian/api` and `notify.py` | no high findings; 19 medium findings, all B608 (SQL built from fixed table and column names; every value is a bound parameter); 28 low (asserts used for type narrowing) |
| pip-audit on the project environment | no known vulnerabilities |
| `mypy --strict` and `ruff` (including the `S` security rules) | clean |

## Not done in this phase

- **OWASP ZAP baseline scan.** Docker is not installed on the development machine. `make zap` runs the baseline scan against the
  OpenAPI document once Docker is available; the exit criterion "baseline scan clean of high findings" is therefore not yet met.
- **Trivy and gitleaks** run in continuous integration (phase 10) and were not run here.
- **TLS, HSTS at the edge, encrypted volumes, non-root containers** belong to deployment (phase 11). The application sends HSTS when
  `MS_ENV=production` and refuses to start without configured secrets in that mode.
- **Mail delivery** uses SMTP (Mailpit in development). Tests capture messages; delivery to a real SMTP server was not exercised.
- **Celery.** Jobs run through `python -m meridian.api.worker` instead (see ADR-009).
- **PDF reports** (WeasyPrint) are phase 6. Reports are HTML and CSV now.
- **Platform settings and the correction review interface** have no dedicated endpoints beyond tenant management and `PATCH /corrections/{id}`.
- Rate limits are fixed windows; a burst at a window boundary can briefly reach twice the limit.


## Phase 6 additions

| Control | Where | Tested by |
|---|---|---|
| Staged uploads are tenant scoped; a reviewer's place pick must be one of the stored candidates | `routers/staged.py`, `services/staging.py` | `test_workflow_assets.py`, `test_api_tenancy.py` |
| Bulk edits are all or nothing and cannot name another tenant's assets | `routers/assets.py` | `test_workflow_assets.py`, `test_api_tenancy.py` |
| Lifecycle transitions are enforced on the server; dismissal needs a reason | `services/lifecycle.py` | `test_workflow_alerts.py` |
| Alert mail and webhooks never carry coordinates; quiet hours hold mail back | `notify.py` | `test_workflow_alerts.py`, `test_workflow_e2e.py` |
| Report and briefing HTML escapes all values and is served with `default-src 'none'` | `services/reports.py` | `test_workflow_alerts.py` |
| PDF renderer refuses every resource except `data:`; map browser has the network blocked; both run in child processes | `services/render.py` | `test_workflow_alerts.py` |
| No third party map tiles, so asset positions are never sent out | `services/maps.py` | `test_workflow_alerts.py` |
| Model written briefing text must match the evidence (numbers, links, names) | `services/briefings.py` | `test_workflow_alerts.py` |
| Briefing email only to users of the tenant; reports and briefing mail are rate limited | `routers/reports.py` | `test_workflow_alerts.py` |
| Corrections leave the tenant only with consent, without tenant ids or free text | `services/corrections.py` | `test_workflow_alerts.py` |

Not done in this phase: report generation runs inside the request (no queue); the alert email has no per-alert unsubscribe link, only the
per-user switch; the browser used for map images is Chromium run with its default sandbox and has not been hardened further.


## Phase 7 additions

| Control | Where | Tested by |
|---|---|---|
| Revenue views readable only through finance-scoped views; the materialized views have no grant for the app role | `0008_metrics.sql` | `test_business_data.py` |
| Revenue endpoints need `revenue.view`; refresh needs `platform.manage` and is rate limited | `routers/revenue.py` | `test_revenue_api.py`, `test_api_roles.py` |
| Platform analytics return counts only (no asset names, positions, or tenant ids) and need `platform.manage` | `routers/analytics.py` | `test_analytics_api.py` |
| Analytics cache keys include the scope; a scoped platform administrator never receives unscoped data | `services/analytics.py` | `test_analytics_api.py` |
| CSV exports neutralise formula characters | `services/analytics.py` | `test_revenue_api.py` |
| Responses are `Cache-Control: private` with an ETag; a route that sets its own header keeps it | `middleware.py` | `test_revenue_api.py` |
| Rollups skip synthetic tenants; loader deletes only tenants it created | `services/rollups.py`, `business/loader.py` | `test_analytics_api.py`, `test_business_data.py` |

Not done in this phase: the analytics cache is per process; the forecast and metric definitions have not been reviewed by a finance specialist.

## Marketing site endpoints (phase 8)

- `POST /newsletter/subscribe` and `POST /contact/demo-request` are unauthenticated and rate limited per address (five per hour). The newsletter answers
  identically for new, pending and confirmed addresses, so it cannot be used to learn who subscribed. Confirmation uses a random token stored hashed.
  The demo request requires explicit consent and keeps a honeypot field.
- `GET /public/stats` returns counts only (places, incidents in 30 days, source records by kind) and is cached for five minutes. It reads no tenant data.
- The web server sends a strict Content Security Policy, `X-Frame-Options: DENY`, `nosniff`, a referrer policy and a permissions policy. Scripts run
  from the web origin only; `'unsafe-inline'` remains in `script-src` for the framework bootstrap until phase 9 adds nonces.
