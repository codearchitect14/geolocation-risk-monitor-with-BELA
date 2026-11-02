"""events_extension

Revision ID: 0005
Revises: 0004
"""

from pathlib import Path

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0005_events_extension.sql"

DOWN = """
DROP TABLE IF EXISTS nws_zone_cache;
ALTER TABLE event_sources DROP COLUMN IF EXISTS details, DROP COLUMN IF EXISTS domain;
ALTER TABLE events DROP COLUMN IF EXISTS expires_at, DROP COLUMN IF EXISTS reliability,
    DROP COLUMN IF EXISTS details, DROP COLUMN IF EXISTS subtype;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWN)
