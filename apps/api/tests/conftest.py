"""Database fixtures: a throwaway database migrated with Alembic for each test session."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from meridian.config import get_settings

API_DIR = Path(__file__).resolve().parents[1]


def _admin_conninfo() -> str:
    info = conninfo_to_dict(get_settings().psycopg_dsn)
    info["dbname"] = "postgres"
    return make_conninfo(**info)


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    try:
        admin = psycopg.connect(_admin_conninfo(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL is not reachable: {exc}")
    name = f"meridian_test_{uuid.uuid4().hex[:8]}"
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    info = conninfo_to_dict(get_settings().psycopg_dsn)
    base = get_settings().database_url.rsplit("/", 1)[0]
    url = f"{base}/{name}"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()
    _ = info


def alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    return config


@pytest.fixture(scope="session")
def migrated_url(test_database_url: str) -> str:
    command.upgrade(alembic_config(), "head")
    return test_database_url


@pytest.fixture
def conn(migrated_url: str) -> Iterator[psycopg.Connection[Any]]:
    from meridian.db import connect

    connection = connect()
    try:
        yield connection
    finally:
        if not connection.closed:
            connection.rollback()
            connection.close()


# -- API fixtures -------------------------------------------------------------------------------------------------------
@pytest.fixture
def api_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from tests.api_support import ENV

    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("MS_DATA_DIR", str(tmp_path / "data"))  # reports and candidate files never touch the repository


@pytest.fixture
def mailer() -> Any:
    from meridian.api.services.mailer import CaptureMailer

    return CaptureMailer()


@pytest.fixture
def world(conn: psycopg.Connection[Any], api_env: None) -> Any:
    from tests.api_support import build_world

    return build_world(conn)


@pytest.fixture
def app(world: Any, mailer: Any) -> Any:
    from meridian.api.main import create_app
    from meridian.api.routers.reports import get_writer
    from meridian.api.security import ratelimit
    from meridian.api.services.mailer import get_mailer

    application = create_app()
    application.dependency_overrides[get_writer] = lambda: None  # tests never depend on the local model server
    ratelimit._backend.reset()  # type: ignore[attr-defined]
    application.dependency_overrides[get_mailer] = lambda: mailer
    return application


@pytest.fixture
def client(app: Any) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as test_client:
        yield test_client


# -- business data fixtures -----------------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def small_files(tmp_path_factory: pytest.TempPathFactory) -> Any:
    import generate_demo_business_data as gen
    from tests.business_support import last_complete_month_end

    directory = tmp_path_factory.mktemp("synthetic_small")
    gen.write_csv(gen.generate(months=24, logo_scale=0.6, end=last_complete_month_end()), directory)
    return directory


@pytest.fixture(scope="session")
def full_files(tmp_path_factory: pytest.TempPathFactory) -> Any:
    import generate_demo_business_data as gen
    from tests.business_support import last_complete_month_end

    directory = tmp_path_factory.mktemp("synthetic_full")
    gen.write_csv(gen.generate(months=36, end=last_complete_month_end()), directory)
    return directory


@pytest.fixture
def business_small(world: Any, conn: psycopg.Connection[Any], small_files: Any) -> Any:
    """24 months of synthetic business history loaded next to the two seeded tenants."""
    from tests.business_support import load_into

    load_into(conn, small_files)
    return small_files


@pytest.fixture
def business_full(world: Any, conn: psycopg.Connection[Any], full_files: Any) -> Any:
    """36 months at full scale, for the performance and exit tests."""
    from tests.business_support import load_into

    load_into(conn, full_files)
    return full_files
