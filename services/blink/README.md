# BLINK service (disabled)

Decision: see `docs/adr/ADR-002-blink.md`. This build does not include BLINK, and the feature flags in
`geo_config_v1` leave it off.

Planned interface, unchanged by that decision:

- `POST /v1/rerank` with `{context, candidates: [{qid, title, description}]}` returns candidate scores.
- `POST /v1/link_assets` with `{tenant_id, text}` returns links to the tenant's private asset catalog.

The pipeline treats a missing service as disabled and does not fail.
