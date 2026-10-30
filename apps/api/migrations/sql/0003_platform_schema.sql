-- Tenancy and security
CREATE TABLE tenants (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name         text NOT NULL,
    slug         text NOT NULL UNIQUE,
    industry     text,
    region       text,
    country_code char(2),
    status       text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'churned')),
    is_demo      boolean NOT NULL DEFAULT true,
    settings     jsonb NOT NULL DEFAULT '{}',
    created_at   timestamptz NOT NULL DEFAULT now(),
    churned_at   timestamptz
);

CREATE TABLE users (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid REFERENCES tenants (id) ON DELETE CASCADE,
    email              text NOT NULL,
    display_name       text NOT NULL,
    password_hash      text NOT NULL,
    role               text NOT NULL CHECK (role IN (
        'viewer', 'analyst', 'manager', 'tenant_admin', 'finance_analyst', 'platform_admin')),
    status             text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'invited')),
    failed_login_count integer NOT NULL DEFAULT 0,
    locked_until       timestamptz,
    last_login_at      timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    -- Platform roles have no tenant; tenant roles must have one.
    CHECK ((role IN ('finance_analyst', 'platform_admin')) = (tenant_id IS NULL))
);
CREATE UNIQUE INDEX users_email_ix ON users (lower(email));
CREATE INDEX users_tenant_ix ON users (tenant_id);

CREATE TABLE user_mfa (
    user_id                uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    totp_secret_encrypted  bytea NOT NULL,
    enabled                boolean NOT NULL DEFAULT false,
    recovery_code_hashes   text[] NOT NULL DEFAULT '{}',
    enrolled_at            timestamptz
);

CREATE TABLE refresh_tokens (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    family_id            uuid NOT NULL,
    token_hash           text NOT NULL UNIQUE,
    issued_at            timestamptz NOT NULL DEFAULT now(),
    expires_at           timestamptz NOT NULL,
    absolute_expires_at  timestamptz NOT NULL,
    revoked_at           timestamptz,
    replaced_by          uuid,
    user_agent           text,
    ip                   inet
);
CREATE INDEX refresh_tokens_user_ix ON refresh_tokens (user_id);
CREATE INDEX refresh_tokens_family_ix ON refresh_tokens (family_id);

CREATE TABLE api_keys (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name          text NOT NULL,
    prefix        text NOT NULL UNIQUE,
    secret_hash   text NOT NULL,
    scopes        text[] NOT NULL DEFAULT '{}',
    created_by    uuid REFERENCES users (id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz,
    last_used_at  timestamptz,
    revoked_at    timestamptz
);
CREATE INDEX api_keys_tenant_ix ON api_keys (tenant_id);

-- Append-only, hash chained. The application role gets INSERT and SELECT only (phase 5).
CREATE TABLE audit_log (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id      uuid,
    actor_user_id  uuid,
    actor_type     text NOT NULL DEFAULT 'user' CHECK (actor_type IN ('user', 'api_key', 'system')),
    action         text NOT NULL,
    object_type    text,
    object_id      text,
    ip             inet,
    request_id     text,
    detail         jsonb NOT NULL DEFAULT '{}',
    created_at     timestamptz NOT NULL DEFAULT now(),
    prev_hash      bytea,
    entry_hash     bytea NOT NULL
);
CREATE INDEX audit_log_tenant_ix ON audit_log (tenant_id, created_at DESC);

-- News and NLP
CREATE TABLE articles (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    url            text NOT NULL,
    url_hash       bytea NOT NULL UNIQUE,
    domain         text,
    title          text,
    snippet        text CHECK (char_length(snippet) <= 300),
    language       text,
    source_country text,
    published_at   timestamptz,
    fetched_at     timestamptz,
    status         text NOT NULL DEFAULT 'discovered',
    text_chars     integer,
    topics         text[] NOT NULL DEFAULT '{}',
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX articles_published_ix ON articles (published_at DESC);

CREATE TABLE article_embeddings (
    article_id uuid PRIMARY KEY REFERENCES articles (id) ON DELETE CASCADE,
    model      text NOT NULL,
    embedding  vector(1024) NOT NULL
);

CREATE TABLE mentions (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id     uuid NOT NULL REFERENCES articles (id) ON DELETE CASCADE,
    span_start     integer NOT NULL,
    span_end       integer NOT NULL CHECK (span_end > span_start),
    surface        text NOT NULL,
    qid            text,
    place_id       bigint REFERENCES places (id),
    md_score       real,
    el_score       real,
    route          text CHECK (route IN ('accept', 'adjudicate', 'fallback', 'unresolved')),
    decision       text,
    model_version  text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mentions_article_ix ON mentions (article_id);
CREATE INDEX mentions_place_ix ON mentions (place_id);

CREATE TABLE mention_candidates (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mention_id       uuid NOT NULL REFERENCES mentions (id) ON DELETE CASCADE,
    rank             smallint NOT NULL,
    place_id         bigint NOT NULL REFERENCES places (id),
    bela_score       real,
    gazetteer_score  real,
    context_score    real,
    blink_score      real,
    llm_label        text,
    UNIQUE (mention_id, rank)
);

-- Events
CREATE TABLE events (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type                 text NOT NULL,
    severity             smallint NOT NULL CHECK (severity BETWEEN 1 AND 4),
    status               text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'developing', 'ongoing', 'resolved')),
    confirmation         text NOT NULL DEFAULT 'unconfirmed' CHECK (confirmation IN ('unconfirmed', 'confirmed')),
    first_seen_at        timestamptz NOT NULL,
    last_seen_at         timestamptz NOT NULL,
    occurred_at          timestamptz,
    title                text NOT NULL,
    summary              text,
    geom                 geometry(Geometry, 4326),
    uncertainty_km       real,
    location_place_id    bigint REFERENCES places (id),
    location_level       text CHECK (location_level IN ('facility', 'city', 'admin2', 'admin1', 'country', 'natural')),
    location_confidence  real CHECK (location_confidence BETWEEN 0 AND 1),
    h3_cell              bigint,
    language_set         text[] NOT NULL DEFAULT '{}',
    reduced_confidence   boolean NOT NULL DEFAULT false,
    config_version       text,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX events_geom_gix ON events USING gist (geom);
CREATE INDEX events_geog_gix ON events USING gist ((geom::geography)) WHERE geom IS NOT NULL;
CREATE INDEX events_time_ix ON events (last_seen_at DESC);
CREATE INDEX events_type_ix ON events (type, severity);
CREATE INDEX events_h3_ix ON events (h3_cell);

CREATE TABLE event_sources (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id     uuid NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    source_kind  text NOT NULL CHECK (source_kind IN ('news', 'usgs', 'nws', 'firms', 'reliefweb')),
    url          text,
    published_at timestamptz,
    source_ref   text NOT NULL,
    article_id   uuid REFERENCES articles (id) ON DELETE SET NULL,
    snippet      text CHECK (char_length(snippet) <= 300),
    reliability  real,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_kind, source_ref)
);
CREATE INDEX event_sources_event_ix ON event_sources (event_id);

CREATE TABLE event_updates (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id     uuid NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    update_type  text NOT NULL,
    detail       jsonb NOT NULL DEFAULT '{}',
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX event_updates_event_ix ON event_updates (event_id, created_at);

-- Assets and alerts (all tenant scoped; row level security is enabled in phase 5)
CREATE TABLE asset_groups (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

CREATE TABLE assets (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name                text NOT NULL,
    type                text NOT NULL CHECK (type IN ('site', 'route', 'region')),
    geom                geometry(Geometry, 4326) NOT NULL,
    criticality         smallint NOT NULL DEFAULT 3 CHECK (criticality BETWEEN 1 AND 5),
    country_code        char(2),
    tags                text[] NOT NULL DEFAULT '{}',
    status              text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    maintenance_windows jsonb NOT NULL DEFAULT '[]',
    external_id         text,
    source_upload_id    uuid,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX assets_tenant_ix ON assets (tenant_id, status);
CREATE INDEX assets_geom_gix ON assets USING gist (geom);
CREATE INDEX assets_geog_gix ON assets USING gist ((geom::geography));
CREATE UNIQUE INDEX assets_external_ix ON assets (tenant_id, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE asset_group_members (
    group_id uuid NOT NULL REFERENCES asset_groups (id) ON DELETE CASCADE,
    asset_id uuid NOT NULL REFERENCES assets (id) ON DELETE CASCADE,
    PRIMARY KEY (group_id, asset_id)
);

CREATE TABLE watch_zones (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name       text NOT NULL,
    geom       geometry(Geometry, 4326) NOT NULL,
    rules      jsonb NOT NULL DEFAULT '{}',
    status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_by uuid REFERENCES users (id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX watch_zones_tenant_ix ON watch_zones (tenant_id);
CREATE INDEX watch_zones_geom_gix ON watch_zones USING gist (geom);

CREATE TABLE exposures (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    event_id             uuid NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    asset_id             uuid NOT NULL REFERENCES assets (id) ON DELETE CASCADE,
    distance_km          real NOT NULL,
    within_uncertainty   boolean NOT NULL,
    score                real NOT NULL CHECK (score BETWEEN 0 AND 1),
    level                text NOT NULL CHECK (level IN ('critical', 'high', 'medium', 'low')),
    components           jsonb NOT NULL DEFAULT '{}',
    config_version       text,
    computed_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (event_id, asset_id)
);
CREATE INDEX exposures_tenant_ix ON exposures (tenant_id, level, score DESC);
CREATE INDEX exposures_asset_ix ON exposures (asset_id);

CREATE TABLE alert_rules (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name           text NOT NULL,
    event_types    text[] NOT NULL DEFAULT '{}',
    min_severity   smallint NOT NULL DEFAULT 1 CHECK (min_severity BETWEEN 1 AND 4),
    min_level      text NOT NULL DEFAULT 'medium' CHECK (min_level IN ('critical', 'high', 'medium', 'low')),
    asset_group_ids uuid[] NOT NULL DEFAULT '{}',
    quiet_hours    jsonb NOT NULL DEFAULT '{}',
    escalation     jsonb NOT NULL DEFAULT '{}',
    enabled        boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX alert_rules_tenant_ix ON alert_rules (tenant_id);

CREATE TABLE alerts (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    event_id          uuid NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    asset_id          uuid REFERENCES assets (id) ON DELETE CASCADE,
    zone_id           uuid REFERENCES watch_zones (id) ON DELETE SET NULL,
    rule_id           uuid REFERENCES alert_rules (id) ON DELETE SET NULL,
    level             text NOT NULL CHECK (level IN ('critical', 'high', 'medium', 'low')),
    status            text NOT NULL DEFAULT 'new' CHECK (status IN (
        'new', 'acknowledged', 'monitoring', 'escalated', 'dismissed', 'resolved')),
    assignee_id       uuid REFERENCES users (id) ON DELETE SET NULL,
    dismissal_reason  text,
    last_score        real,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (status <> 'dismissed' OR dismissal_reason IS NOT NULL)
);
CREATE UNIQUE INDEX alerts_dedup_ix ON alerts (tenant_id, event_id, asset_id) NULLS NOT DISTINCT;
CREATE INDEX alerts_queue_ix ON alerts (tenant_id, status, level, created_at DESC);

CREATE TABLE alert_events (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_id       uuid NOT NULL REFERENCES alerts (id) ON DELETE CASCADE,
    tenant_id      uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    actor_user_id  uuid REFERENCES users (id) ON DELETE SET NULL,
    kind           text NOT NULL CHECK (kind IN ('created', 'status_change', 'comment', 'assignment', 'update', 'notification')),
    detail         jsonb NOT NULL DEFAULT '{}',
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX alert_events_alert_ix ON alert_events (alert_id, created_at);

CREATE TABLE briefings (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    kind          text NOT NULL CHECK (kind IN ('daily', 'weekly', 'custom')),
    period_start  timestamptz NOT NULL,
    period_end    timestamptz NOT NULL,
    evidence      jsonb NOT NULL DEFAULT '{}',
    narrative     text,
    model_version text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX briefings_tenant_ix ON briefings (tenant_id, created_at DESC);

CREATE TABLE reports (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('incident', 'portfolio')),
    event_id    uuid REFERENCES events (id) ON DELETE SET NULL,
    params      jsonb NOT NULL DEFAULT '{}',
    status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ready', 'failed')),
    file_ref    text,
    created_by  uuid REFERENCES users (id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reports_tenant_ix ON reports (tenant_id, created_at DESC);

CREATE TABLE correction_requests (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid REFERENCES tenants (id) ON DELETE SET NULL,
    event_id         uuid NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    kind             text NOT NULL CHECK (kind IN ('wrong_location', 'wrong_type', 'duplicate')),
    details          jsonb NOT NULL DEFAULT '{}',
    status           text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'accepted', 'rejected')),
    consent_for_gold boolean NOT NULL DEFAULT false,
    submitted_by     uuid REFERENCES users (id) ON DELETE SET NULL,
    reviewed_by      uuid REFERENCES users (id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    reviewed_at      timestamptz
);
CREATE INDEX correction_requests_status_ix ON correction_requests (status, created_at);

-- Business (synthetic demo data). Materialized views are created in phase 7 with the metric definitions.
CREATE TABLE plans (
    id                 text PRIMARY KEY,
    name               text NOT NULL,
    monthly_price      numeric(12, 2) NOT NULL,
    asset_limit        integer NOT NULL,
    overage_unit_size  integer NOT NULL DEFAULT 25,
    overage_unit_price numeric(12, 2) NOT NULL DEFAULT 0
);

CREATE TABLE subscriptions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    plan_id       text NOT NULL REFERENCES plans (id),
    billing_cycle text NOT NULL CHECK (billing_cycle IN ('monthly', 'annual')),
    price         numeric(12, 2) NOT NULL,
    start_date    date NOT NULL,
    end_date      date,
    change_reason text,
    CHECK (end_date IS NULL OR end_date >= start_date)
);
CREATE INDEX subscriptions_tenant_ix ON subscriptions (tenant_id, start_date);

CREATE TABLE invoices (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    period_start  date NOT NULL,
    period_end    date NOT NULL,
    status        text NOT NULL CHECK (status IN ('paid', 'open', 'overdue')),
    total         numeric(12, 2) NOT NULL,
    issued_at     date NOT NULL,
    due_at        date NOT NULL,
    paid_at       date
);
CREATE INDEX invoices_tenant_ix ON invoices (tenant_id, period_start);

CREATE TABLE invoice_lines (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id  uuid NOT NULL REFERENCES invoices (id) ON DELETE CASCADE,
    line_type   text NOT NULL CHECK (line_type IN ('subscription', 'overage', 'credit')),
    description text NOT NULL,
    amount      numeric(12, 2) NOT NULL
);
CREATE INDEX invoice_lines_invoice_ix ON invoice_lines (invoice_id);

CREATE TABLE usage_daily (
    tenant_id         uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    date              date NOT NULL,
    assets_monitored  integer NOT NULL DEFAULT 0,
    alerts            integer NOT NULL DEFAULT 0,
    briefings         integer NOT NULL DEFAULT 0,
    api_calls         integer NOT NULL DEFAULT 0,
    uploads           integer NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, date)
);

CREATE TABLE ops_stats_daily (
    tenant_id           uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    date                date NOT NULL,
    alerts_by_level     jsonb NOT NULL DEFAULT '{}',
    acknowledged        integer NOT NULL DEFAULT 0,
    dismissed           integer NOT NULL DEFAULT 0,
    location_confirmed  integer NOT NULL DEFAULT 0,
    location_corrected  integer NOT NULL DEFAULT 0,
    median_ack_minutes  real,
    PRIMARY KEY (tenant_id, date)
);

CREATE TABLE platform_stats_daily (
    date                           date PRIMARY KEY,
    incidents_ingested             integer NOT NULL DEFAULT 0,
    p50_latency_ms                 real,
    p95_latency_ms                 real,
    detection_delay_minutes_median real,
    false_alert_rate               real
);

CREATE TABLE marketing_spend (
    month   date NOT NULL,
    channel text NOT NULL,
    spend   numeric(12, 2) NOT NULL,
    PRIMARY KEY (month, channel)
);

CREATE TABLE business_events (
    id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date  date NOT NULL,
    label text NOT NULL
);
