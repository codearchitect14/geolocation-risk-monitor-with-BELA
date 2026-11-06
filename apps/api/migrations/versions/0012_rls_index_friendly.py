"""index friendly row level security

Revision ID: 0012
Revises: 0011
"""

from pathlib import Path

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0012_rls_index_friendly.sql"

DOWNGRADE = """
DO $do$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['assets', 'asset_groups', 'watch_zones', 'exposures', 'alert_rules', 'alerts', 'alert_events',
                             'briefings', 'reports', 'uploads', 'webhooks', 'webhook_deliveries', 'idempotency_keys', 'api_keys']
    LOOP
        EXECUTE format('DROP POLICY platform_all ON %I', t);
        EXECUTE format('ALTER POLICY tenant_isolation ON %I USING (tenant_id = app_tenant() OR app_bypass()) WITH CHECK (tenant_id = app_tenant() OR app_bypass())', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['usage_daily', 'ops_stats_daily']
    LOOP
        EXECUTE format('DROP POLICY platform_all ON %I', t);
        EXECUTE format('ALTER POLICY tenant_isolation ON %I USING (tenant_id = app_tenant() OR app_bypass())', t);
    END LOOP;
END
$do$;
DROP INDEX IF EXISTS assets_tenant_page_ix;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL.read_text(encoding="utf-8").replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE.replace("%", "%%"))
