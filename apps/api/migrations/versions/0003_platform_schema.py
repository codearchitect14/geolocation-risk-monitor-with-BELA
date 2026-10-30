"""platform_schema

Revision ID: 0003
Revises: 0002
"""

from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0003_platform_schema.sql"

DOWN = """
DROP TABLE IF EXISTS business_events, marketing_spend, platform_stats_daily, ops_stats_daily, usage_daily,
    invoice_lines, invoices, subscriptions, plans, correction_requests, reports, briefings, alert_events,
    alerts, alert_rules, exposures, watch_zones, asset_group_members, assets, asset_groups, event_updates,
    event_sources, events, mention_candidates, mentions, article_embeddings, articles, audit_log, api_keys,
    refresh_tokens, user_mfa, users, tenants CASCADE;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWN)
