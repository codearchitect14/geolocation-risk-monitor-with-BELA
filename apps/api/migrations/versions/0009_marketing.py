"""marketing

Revision ID: 0009
Revises: 0008
"""

from pathlib import Path

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0009_marketing.sql"

DOWN = """
DROP TABLE IF EXISTS newsletter_subscribers;
ALTER TABLE demo_requests DROP COLUMN IF EXISTS consent_at, DROP COLUMN IF EXISTS industry, DROP COLUMN IF EXISTS role;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL.read_text(encoding="utf-8").replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWN.replace("%", "%%"))
