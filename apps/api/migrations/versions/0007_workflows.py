"""workflows

Revision ID: 0007
Revises: 0006
"""

from pathlib import Path

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0007_workflows.sql"

DOWN = """
REVOKE SELECT ON mentions FROM meridian_app;
ALTER TABLE assets DROP COLUMN IF EXISTS location_source, DROP COLUMN IF EXISTS location_uncertainty_km, DROP COLUMN IF EXISTS place_id;
ALTER TABLE correction_requests DROP COLUMN IF EXISTS gold_exported_at;
DROP INDEX IF EXISTS briefings_period_ix;
ALTER TABLE briefings DROP COLUMN IF EXISTS delivered_at;
ALTER TABLE users DROP COLUMN IF EXISTS notify_email;
ALTER TABLE alerts DROP COLUMN IF EXISTS acknowledged_at, DROP COLUMN IF EXISTS escalated_at;
UPDATE uploads SET status = 'failed' WHERE status IN ('staged', 'cancelled');
ALTER TABLE uploads DROP COLUMN IF EXISTS mapping, DROP COLUMN IF EXISTS staged, DROP COLUMN IF EXISTS committed_at;
ALTER TABLE uploads DROP CONSTRAINT IF EXISTS uploads_status_check;
ALTER TABLE uploads ADD CONSTRAINT uploads_status_check CHECK (status IN ('processed', 'partial', 'failed'));
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL.read_text(encoding="utf-8").replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWN.replace("%", "%%"))
