"""api_security

Revision ID: 0006
Revises: 0005
"""

from pathlib import Path

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0006_api_security.sql"

DOWN = """
DO $do$
DECLARE
    r record;
BEGIN
    FOR r IN SELECT schemaname, tablename, policyname FROM pg_policies WHERE schemaname = 'public' LOOP
        EXECUTE format('DROP POLICY %I ON %I.%I', r.policyname, r.schemaname, r.tablename);
    END LOOP;
END
$do$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM meridian_app;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM meridian_app;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM meridian_app;
REVOKE USAGE ON SCHEMA public FROM meridian_app;
ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS last_used_at;
ALTER TABLE users DROP COLUMN IF EXISTS password_changed_at;
DROP TABLE IF EXISTS demo_requests, password_reset_tokens, webhook_deliveries, webhooks, idempotency_keys, uploads CASCADE;
DROP TRIGGER IF EXISTS audit_chain_bi ON audit_log;
DROP TRIGGER IF EXISTS audit_no_change ON audit_log;
DROP TRIGGER IF EXISTS audit_no_truncate ON audit_log;
DROP FUNCTION IF EXISTS audit_verify(), audit_chain(), audit_immutable(), audit_entry_hash(audit_log, bytea);
ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY;
ALTER TABLE users DISABLE ROW LEVEL SECURITY;
ALTER TABLE tenants DISABLE ROW LEVEL SECURITY;
ALTER TABLE correction_requests DISABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions DISABLE ROW LEVEL SECURITY;
ALTER TABLE invoices DISABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_lines DISABLE ROW LEVEL SECURITY;
ALTER TABLE asset_group_members DISABLE ROW LEVEL SECURITY;
ALTER TABLE assets DISABLE ROW LEVEL SECURITY;
ALTER TABLE asset_groups DISABLE ROW LEVEL SECURITY;
ALTER TABLE watch_zones DISABLE ROW LEVEL SECURITY;
ALTER TABLE exposures DISABLE ROW LEVEL SECURITY;
ALTER TABLE alert_rules DISABLE ROW LEVEL SECURITY;
ALTER TABLE alerts DISABLE ROW LEVEL SECURITY;
ALTER TABLE alert_events DISABLE ROW LEVEL SECURITY;
ALTER TABLE briefings DISABLE ROW LEVEL SECURITY;
ALTER TABLE reports DISABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys DISABLE ROW LEVEL SECURITY;
ALTER TABLE usage_daily DISABLE ROW LEVEL SECURITY;
ALTER TABLE ops_stats_daily DISABLE ROW LEVEL SECURITY;
ALTER TABLE platform_stats_daily DISABLE ROW LEVEL SECURITY;
ALTER TABLE marketing_spend DISABLE ROW LEVEL SECURITY;
ALTER TABLE business_events DISABLE ROW LEVEL SECURITY;
DROP FUNCTION IF EXISTS app_tenant(), app_user(), app_role(), app_bypass();
"""


def upgrade() -> None:
    # The driver treats percent signs as placeholders; format() in the SQL needs them doubled.
    op.get_bind().exec_driver_sql(SQL.read_text(encoding="utf-8").replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWN.replace("%", "%%"))
