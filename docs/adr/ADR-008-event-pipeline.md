# ADR-008: Event pipeline, exposure scoring, and alerts

- Status: accepted
- Date: 2026-11-02

## Context

Phase 4 turns hazard feeds and news into events, scores each event against tenant assets, and raises alerts. Three needs
shape the design: feeds are authoritative for place and time, news is fast but noisy, and no automated step may alert on a
language model decision alone.

## Decisions

- **One event schema, one record per source.** Every USGS, NWS, FIRMS, ReliefWeb, and news record becomes a
  `NormalizedEvent` with a stable `(source_kind, source_ref)`. Re-reading a file is a no-op, a changed record is a revision,
  and an NWS update or cancellation is attached through its `supersedes` references. An event has many sources.
- **Clustering is geometric first.** A new record joins an existing event only if the type and subtype are compatible, the
  record falls in the type's time window (48 hours by default, per-type overrides), and the distance is within the sum of
  both uncertainties (with a per-type minimum, capped at 400 km). Two news reports additionally need a title similarity of
  0.62 or more. Two records from the same feed (USGS, FIRMS, ReliefWeb) are always distinct incidents. H3 res 7 is a
  tie-break, not a filter: PostGIS `ST_DWithin` on geography is exact and uses the index.
- **Feed geometry wins.** A feed location replaces a news location, then higher confidence, then smaller uncertainty.
- **Reliability is noisy-or over independent sources** (distinct feeds or distinct news outlets), capped at 0.99. An event
  is `confirmed` with two independent sources. A single news report has reliability 0.60, so it rarely reaches `high`.
- **The model labels, rules decide.** The local model returns type, subtype, severity 1 to 4, and a private-person flag
  under a JSON schema. Reports about a named private person and non-disruptions are dropped before any event exists.
  Alerts come only from the exposure formula and tenant rules. Article text is delimited and treated as data.
- **Exposure is explicit.** `type_weight * severity_weight * proximity * location_confidence * source_reliability *
  recency_decay * criticality_factor`, every component stored with the score. Proximity is 1 inside the combined
  uncertainty and `exp(-(d - u) / lambda)` beyond it, lambda by type (and magnitude for earthquakes). Country-level events
  are never matched to site assets.
- **Alerts are idempotent.** One alert per tenant, event, and asset. A later exposure updates it only when the level rises
  or the score rises by 0.10; detail-only changes do nothing; a dismissed alert reopens only after a two-level climb.
  Maintenance windows suppress alerts. Watch zones raise one zone alert per tenant and event.
- **Versioned rules.** All thresholds, weights, mappings, and windows are in `events_config_v1.yaml`; changes go in a new
  file, and rows record the version.

## Consequences

- A bare headline place with the model stage off can pick the wrong sense of an ambiguous name. The pipeline relies on the
  adjudication stage and on body mentions; the end-to-end test uses headlines with a qualifier for that reason.
- Single news reports on a large uncertainty alert wide areas at low levels. Precision at `medium` on synthetic scenarios is
  about 0.46 (see `docs/events_report.md`); tightening needs real labeled events.
- Unreliable inputs (future dates, malformed rows) are dropped and counted, never stored.
