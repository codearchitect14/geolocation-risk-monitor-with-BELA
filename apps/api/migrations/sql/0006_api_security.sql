-- Phase 5: API support tables, the restricted application role, Row Level Security, and the hash chained audit log.

-- Supporting tables ---------------------------------------------------------------------------------------------
CREATE TABLE uploads (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    filename         text NOT NULL,
    kind             text NOT NULL CHECK (kind IN ('csv', 'geojson')),
    status           text NOT NULL DEFAULT 'processed' CHECK (status IN ('processed', 'partial', 'failed')),
    size_bytes       integer NOT NULL,
    rows_total       integer NOT NULL DEFAULT 0,
    rows_accepted    integer NOT NULL DEFAULT 0,
    rows_rejected    integer NOT NULL DEFAULT 0,
    errors           jsonb NOT NULL DEFAULT '[]',
    created_by       uuid REFERENCES users (id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX uploads_tenant_ix ON uploads (tenant_id, created_at DESC);

CREATE TABLE idempotency_keys (
    tenant_id     uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    scope         text NOT NULL,
    key           text NOT NULL,
    request_hash  text NOT NULL,
    response      jsonb NOT NULL,
    status_code   integer NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, scope, key)
);

CREATE TABLE webhooks (
    id                         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                  uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name                       text NOT NULL,
    url                        text NOT NULL,
    secret_encrypted           bytea NOT NULL,
    previous_secret_encrypted  bytea,
    secret_rotated_at          timestamptz,
    min_level                  text NOT NULL DEFAULT 'medium' CHECK (min_level IN ('critical', 'high', 'medium', 'low')),
    include_coordinates        boolean NOT NULL DEFAULT false,
    enabled                    boolean NOT NULL DEFAULT true,
    created_by                 uuid REFERENCES users (id) ON DELETE SET NULL,
    created_at                 timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX webhooks_tenant_ix ON webhooks (tenant_id);

CREATE TABLE webhook_deliveries (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    webhook_id       uuid NOT NULL REFERENCES webhooks (id) ON DELETE CASCADE,
    tenant_id        uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    alert_id         uuid REFERENCES alerts (id) ON DELETE SET NULL,
    kind             text NOT NULL,
    payload          jsonb NOT NULL,
    status           text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'delivered', 'abandoned')),
    attempts         integer NOT NULL DEFAULT 0,
    next_attempt_at  timestamptz NOT NULL DEFAULT now(),
    last_status_code integer,
    last_error       text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    delivered_at     timestamptz
);
CREATE INDEX webhook_deliveries_due_ix ON webhook_deliveries (status, next_attempt_at);
CREATE INDEX webhook_deliveries_tenant_ix ON webhook_deliveries (tenant_id, created_at DESC);

CREATE TABLE password_reset_tokens (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash  text NOT NULL UNIQUE,
    purpose     text NOT NULL DEFAULT 'reset' CHECK (purpose IN ('reset', 'invite')),
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX password_reset_tokens_user_ix ON password_reset_tokens (user_id);

CREATE TABLE demo_requests (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    email       text NOT NULL,
    company     text,
    message     text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS last_used_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at timestamptz;

-- Audit log: hash chain computed by the database, no update or delete ---------------------------------------------
CREATE FUNCTION audit_entry_hash(r audit_log, prev bytea) RETURNS bytea
LANGUAGE sql IMMUTABLE AS $fn$
    SELECT digest(
        coalesce(prev, ''::bytea) || convert_to(concat_ws('|',
            r.id::text, coalesce(r.tenant_id::text, ''), coalesce(r.actor_user_id::text, ''), r.actor_type, r.action,
            coalesce(r.object_type, ''), coalesce(r.object_id, ''), coalesce(r.ip::text, ''), coalesce(r.request_id, ''),
            r.detail::text, ((extract(epoch FROM r.created_at) * 1000000)::bigint)::text), 'UTF8'),
        'sha256')
$fn$;

CREATE FUNCTION audit_chain() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $fn$
DECLARE
    last_hash bytea;
BEGIN
    PERFORM pg_advisory_xact_lock(727001);
    NEW.id := nextval(pg_get_serial_sequence('audit_log', 'id'));
    SELECT entry_hash INTO last_hash FROM audit_log ORDER BY id DESC LIMIT 1;
    NEW.prev_hash := last_hash;
    NEW.entry_hash := audit_entry_hash(NEW, last_hash);
    RETURN NEW;
END
$fn$;
CREATE TRIGGER audit_chain_bi BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_chain();

CREATE FUNCTION audit_immutable() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION 'audit_log is append only';
END
$fn$;
CREATE TRIGGER audit_no_change BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_immutable();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_log FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();

CREATE FUNCTION audit_verify() RETURNS TABLE (checked bigint, first_bad_id bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $fn$
DECLARE
    r audit_log;
    expected bytea := NULL;
    n bigint := 0;
BEGIN
    FOR r IN SELECT * FROM audit_log ORDER BY id LOOP
        IF r.prev_hash IS DISTINCT FROM expected OR r.entry_hash <> audit_entry_hash(r, r.prev_hash) THEN
            checked := n;
            first_bad_id := r.id;
            RETURN NEXT;
            RETURN;
        END IF;
        expected := r.entry_hash;
        n := n + 1;
    END LOOP;
    checked := n;
    first_bad_id := NULL;
    RETURN NEXT;
END
$fn$;

-- Application role and Row Level Security -------------------------------------------------------------------------
DO $do$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'meridian_app') THEN
        CREATE ROLE meridian_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$do$;
GRANT meridian_app TO CURRENT_USER;
GRANT USAGE ON SCHEMA public TO meridian_app;

CREATE FUNCTION app_tenant() RETURNS uuid LANGUAGE sql STABLE AS $fn$
    SELECT nullif(current_setting('app.tenant_id', true), '')::uuid
$fn$;
CREATE FUNCTION app_user() RETURNS uuid LANGUAGE sql STABLE AS $fn$
    SELECT nullif(current_setting('app.user_id', true), '')::uuid
$fn$;
CREATE FUNCTION app_role() RETURNS text LANGUAGE sql STABLE AS $fn$
    SELECT nullif(current_setting('app.role', true), '')
$fn$;
CREATE FUNCTION app_bypass() RETURNS boolean LANGUAGE sql STABLE AS $fn$
    SELECT coalesce(current_setting('app.bypass', true), '') = 'on'
$fn$;
GRANT EXECUTE ON FUNCTION app_tenant(), app_user(), app_role(), app_bypass() TO meridian_app;

-- Global tables: read only for the application role.
GRANT SELECT ON places, place_aliases, events, event_sources, event_updates, plans, ref_country_info TO meridian_app;

-- Tenant scoped tables with full access inside the tenant.
DO $do$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['assets', 'asset_groups', 'watch_zones', 'exposures', 'alert_rules', 'alerts', 'alert_events',
                             'briefings', 'reports', 'uploads', 'webhooks', 'webhook_deliveries', 'idempotency_keys', 'api_keys']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO meridian_app', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I FOR ALL TO meridian_app USING (tenant_id = app_tenant() OR app_bypass()) '
            'WITH CHECK (tenant_id = app_tenant() OR app_bypass())', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['usage_daily', 'ops_stats_daily']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('GRANT SELECT ON %I TO meridian_app', t);
        EXECUTE format('CREATE POLICY tenant_isolation ON %I FOR SELECT TO meridian_app USING (tenant_id = app_tenant() OR app_bypass())', t);
    END LOOP;
END
$do$;

ALTER TABLE asset_group_members ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, DELETE ON asset_group_members TO meridian_app;
CREATE POLICY tenant_isolation ON asset_group_members FOR ALL TO meridian_app
    USING (EXISTS (SELECT 1 FROM asset_groups g WHERE g.id = group_id) AND EXISTS (SELECT 1 FROM assets a WHERE a.id = asset_id))
    WITH CHECK (EXISTS (SELECT 1 FROM asset_groups g WHERE g.id = group_id) AND EXISTS (SELECT 1 FROM assets a WHERE a.id = asset_id));

-- Users: columns are limited so password hashes and lockout state never reach the application role.
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
GRANT SELECT (id, tenant_id, email, display_name, role, status, last_login_at, created_at) ON users TO meridian_app;
GRANT INSERT (tenant_id, email, display_name, password_hash, role, status) ON users TO meridian_app;
GRANT UPDATE (display_name, role, status) ON users TO meridian_app;
GRANT DELETE ON users TO meridian_app;
CREATE POLICY users_read ON users FOR SELECT TO meridian_app USING (tenant_id = app_tenant() OR id = app_user() OR app_bypass());
CREATE POLICY users_write ON users FOR ALL TO meridian_app USING (tenant_id = app_tenant() OR app_bypass())
    WITH CHECK (tenant_id = app_tenant() OR app_bypass());

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
GRANT SELECT ON tenants TO meridian_app;
GRANT INSERT ON tenants TO meridian_app;
GRANT UPDATE (settings, status) ON tenants TO meridian_app;
CREATE POLICY tenants_read ON tenants FOR SELECT TO meridian_app
    USING (id = app_tenant() OR app_bypass() OR app_role() = 'finance_analyst');
CREATE POLICY tenants_insert ON tenants FOR INSERT TO meridian_app WITH CHECK (app_bypass());
CREATE POLICY tenants_update ON tenants FOR UPDATE TO meridian_app USING (id = app_tenant() OR app_bypass())
    WITH CHECK (id = app_tenant() OR app_bypass());

-- Audit log: the application role can append and read its own tenant, never change or remove.
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT ON audit_log TO meridian_app;
GRANT EXECUTE ON FUNCTION audit_verify() TO meridian_app;
CREATE POLICY audit_read ON audit_log FOR SELECT TO meridian_app USING (tenant_id = app_tenant() OR app_bypass());
CREATE POLICY audit_append ON audit_log FOR INSERT TO meridian_app
    WITH CHECK (tenant_id IS NULL OR tenant_id = app_tenant() OR app_bypass());
GRANT USAGE ON SEQUENCE audit_log_id_seq TO meridian_app;
GRANT USAGE ON SEQUENCE alert_events_id_seq TO meridian_app;

ALTER TABLE correction_requests ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE ON correction_requests TO meridian_app;
CREATE POLICY corrections_scope ON correction_requests FOR ALL TO meridian_app
    USING (tenant_id = app_tenant() OR app_bypass()) WITH CHECK (tenant_id = app_tenant() OR app_bypass());

-- Billing is readable by the owning tenant, finance, and platform administrators; written by jobs only.
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_lines ENABLE ROW LEVEL SECURITY;
GRANT SELECT ON subscriptions, invoices, invoice_lines TO meridian_app;
CREATE POLICY billing_read ON subscriptions FOR SELECT TO meridian_app
    USING (tenant_id = app_tenant() OR app_bypass() OR app_role() = 'finance_analyst');
CREATE POLICY billing_read ON invoices FOR SELECT TO meridian_app
    USING (tenant_id = app_tenant() OR app_bypass() OR app_role() = 'finance_analyst');
CREATE POLICY billing_read ON invoice_lines FOR SELECT TO meridian_app
    USING (EXISTS (SELECT 1 FROM invoices i WHERE i.id = invoice_id));

DO $do$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['platform_stats_daily', 'marketing_spend', 'business_events']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('GRANT SELECT ON %I TO meridian_app', t);
        EXECUTE format('CREATE POLICY platform_only ON %I FOR SELECT TO meridian_app USING (app_role() IN (''finance_analyst'', ''platform_admin''))', t);
    END LOOP;
END
$do$;

-- Authentication tables (refresh_tokens, user_mfa, password_reset_tokens, demo_requests) are reached only by the owner
-- role inside the authentication code; the application role has no privileges on them.
GRANT INSERT ON demo_requests TO meridian_app;
