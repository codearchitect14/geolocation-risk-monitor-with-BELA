"""candidate visibility

Revision ID: 0010
Revises: 0009
"""

from pathlib import Path

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0010_candidate_visibility.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL.read_text(encoding="utf-8").replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("REVOKE SELECT ON mention_candidates FROM meridian_app;")
