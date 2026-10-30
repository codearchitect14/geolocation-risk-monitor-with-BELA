"""places

Revision ID: 0002
Revises: 0001
"""

from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0002_places.sql"

DOWN = """
DROP TABLE IF EXISTS etl_runs, place_hierarchy_issues, place_merge_review, place_embeddings,
    place_aliases, places, place_uncertainty_rules, ref_admin1, ref_countries, ref_country_info CASCADE;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWN)
