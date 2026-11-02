-- Event details needed by the event pipeline (phase 4).
ALTER TABLE events
    ADD COLUMN subtype      text,
    ADD COLUMN details      jsonb NOT NULL DEFAULT '{}',
    ADD COLUMN reliability  real CHECK (reliability BETWEEN 0 AND 1),
    ADD COLUMN expires_at   timestamptz;
CREATE INDEX events_status_ix ON events (status, last_seen_at DESC);

ALTER TABLE event_sources
    ADD COLUMN domain  text,
    ADD COLUMN details jsonb NOT NULL DEFAULT '{}';
CREATE INDEX event_sources_published_ix ON event_sources (published_at);

-- Polygons of National Weather Service zones, fetched once and reused (alerts often carry no geometry).
CREATE TABLE nws_zone_cache (
    zone_url   text PRIMARY KEY,
    status     text NOT NULL CHECK (status IN ('ok', 'missing', 'error')),
    geom       geometry(Geometry, 4326),
    fetched_at timestamptz NOT NULL DEFAULT now()
);
