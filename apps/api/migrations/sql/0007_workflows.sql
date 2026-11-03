-- Phase 6 product workflows: staged uploads, alert lifecycle timestamps, notification preference, briefing delivery.

ALTER TABLE uploads DROP CONSTRAINT IF EXISTS uploads_status_check;
ALTER TABLE uploads ADD CONSTRAINT uploads_status_check
    CHECK (status IN ('staged', 'processed', 'partial', 'failed', 'cancelled'));
ALTER TABLE uploads
    ADD COLUMN mapping      jsonb NOT NULL DEFAULT '{}',
    ADD COLUMN staged       jsonb NOT NULL DEFAULT '[]',
    ADD COLUMN committed_at timestamptz;

ALTER TABLE assets
    ADD COLUMN location_source text NOT NULL DEFAULT 'provided' CHECK (location_source IN ('provided', 'place')),
    ADD COLUMN location_uncertainty_km real,
    ADD COLUMN place_id bigint REFERENCES places (id) ON DELETE SET NULL;

ALTER TABLE alerts
    ADD COLUMN acknowledged_at timestamptz,
    ADD COLUMN escalated_at    timestamptz;

ALTER TABLE users ADD COLUMN notify_email boolean NOT NULL DEFAULT true;
GRANT SELECT (notify_email) ON users TO meridian_app;
GRANT UPDATE (notify_email) ON users TO meridian_app;

ALTER TABLE briefings ADD COLUMN delivered_at timestamptz;
CREATE UNIQUE INDEX briefings_period_ix ON briefings (tenant_id, kind, period_start) WHERE kind <> 'custom';

ALTER TABLE correction_requests ADD COLUMN gold_exported_at timestamptz;

-- Incident detail shows the places that were linked in the source articles (public reference data).
GRANT SELECT ON mentions TO meridian_app;
