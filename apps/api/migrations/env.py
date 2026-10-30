"""Alembic environment. The URL comes from DATABASE_URL or the repository .env file."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from meridian.config import get_settings

config = context.config


def run_migrations_offline() -> None:
    context.configure(url=get_settings().database_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
