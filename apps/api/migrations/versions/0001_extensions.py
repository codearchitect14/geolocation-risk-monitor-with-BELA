"""extensions

Revision ID: 0001
Revises: none
"""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0001_extensions.sql"

DOWN = """
DROP EXTENSION IF EXISTS pgcrypto;
DROP EXTENSION IF EXISTS pg_trgm;
DROP EXTENSION IF EXISTS vector;
DROP EXTENSION IF EXISTS postgis CASCADE;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWN)
