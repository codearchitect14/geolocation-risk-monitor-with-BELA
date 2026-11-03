"""metrics

Revision ID: 0008
Revises: 0007
"""

from pathlib import Path

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0008_metrics.sql"

DOWN = """
DROP FUNCTION IF EXISTS refresh_metrics();
DROP VIEW IF EXISTS metric_refresh_v, unit_economics_monthly_v, overage_monthly_v, revenue_by_dimension_v, cohort_retention_v,
    retention_monthly_v, mrr_monthly_v, mrr_movements_v, tenant_mrr_monthly_v;
DROP FUNCTION IF EXISTS finance_scope();
DROP VIEW IF EXISTS unit_economics_monthly, overage_monthly;
DROP MATERIALIZED VIEW IF EXISTS revenue_by_dimension, cohort_retention, retention_monthly, mrr_monthly, mrr_movements, tenant_mrr_monthly;
DROP TABLE IF EXISTS metric_refresh;
DROP FUNCTION IF EXISTS region_of_country(text), last_complete_month(), gross_margin();
ALTER TABLE tenants DROP COLUMN IF EXISTS acquisition_channel;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL.read_text(encoding="utf-8").replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWN.replace("%", "%%"))
