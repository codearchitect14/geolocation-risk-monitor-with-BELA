-- Tenant isolation policies that the planner can use with an index.
--
-- The original policy was `tenant_id = app_tenant() OR app_bypass()`. The OR with a row-independent test cannot become an
-- index condition, so every tenant query on a large table scanned the whole table (82,000 asset rows for a tenant with 5,000).
-- Platform staff now run as a separate role (`meridian_platform`, a member of `meridian_app`) that has its own allow-all
-- policy, and the policy for `meridian_app` is the plain equality, which an index on tenant_id serves.
DO $do$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'meridian_platform') THEN
        CREATE ROLE meridian_platform NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$do$;
GRANT meridian_app TO meridian_platform;
GRANT meridian_platform TO CURRENT_USER;

DO $do$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['assets', 'asset_groups', 'watch_zones', 'exposures', 'alert_rules', 'alerts', 'alert_events',
                             'briefings', 'reports', 'uploads', 'webhooks', 'webhook_deliveries', 'idempotency_keys', 'api_keys']
    LOOP
        EXECUTE format('ALTER POLICY tenant_isolation ON %I USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant())', t);
        EXECUTE format('CREATE POLICY platform_all ON %I FOR ALL TO meridian_platform USING (true) WITH CHECK (true)', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['usage_daily', 'ops_stats_daily']
    LOOP
        EXECUTE format('ALTER POLICY tenant_isolation ON %I USING (tenant_id = app_tenant())', t);
        EXECUTE format('CREATE POLICY platform_all ON %I FOR SELECT TO meridian_platform USING (true)', t);
    END LOOP;
END
$do$;

-- Keyset paging of the asset list: newest first within a tenant and status.
CREATE INDEX assets_tenant_page_ix ON assets (tenant_id, status, created_at DESC, id DESC);
