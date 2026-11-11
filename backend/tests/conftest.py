"""Shared pytest fixtures for database-backed tests.

Database tests run against a throwaway PostgreSQL database that is created
on the server named by ``DATABASE_URL`` (or ``TEST_DATABASE_URL``) and
dropped when the test session ends. The development database itself is
never modified: Alembic applies migrations to the throwaway database only.

If PostgreSQL is not reachable, database tests are skipped with a hint to
start it via ``docker compose up -d``.
"""

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from mcp import Client
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_db_session
from app.core.config import get_settings
from app.main import app
from app.models import Experiment
from mcp_server import server as mcp_server_module

BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def _server_url() -> URL:
    """URL of the PostgreSQL server that hosts the test database."""
    raw = os.environ.get("TEST_DATABASE_URL") or get_settings().database_url
    return make_url(raw)


@pytest.fixture(scope="session")
def admin_engine() -> Iterator[Engine]:
    """Engine connected to the server's administrative database."""
    engine = create_engine(_server_url().set(database="postgres"))
    try:
        with engine.connect():
            pass
    except sa.exc.OperationalError:
        engine.dispose()
        pytest.skip(
            "PostgreSQL is not reachable — start it with `docker compose up -d`"
        )
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def test_database_url(admin_engine: Engine) -> Iterator[str]:
    """Create an isolated database for the test session; drop it afterwards."""
    server_url = _server_url()
    database_name = f"growthloop_test_{uuid.uuid4().hex[:8]}"

    with admin_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(sa.text(f'CREATE DATABASE "{database_name}"'))
    try:
        yield server_url.set(database=database_name).render_as_string(
            hide_password=False
        )
    finally:
        with admin_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.execute(
                sa.text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )


@pytest.fixture(scope="session")
def alembic_config(test_database_url: str) -> Config:
    """Alembic configuration pointed at the isolated test database."""
    config = Config(str(ALEMBIC_INI))
    # Absolute paths so the suite works regardless of the current directory.
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", test_database_url)
    return config


@pytest.fixture(scope="session")
def migrated_engine(alembic_config: Config, test_database_url: str) -> Iterator[Engine]:
    """Engine for the test database, with all migrations applied."""
    command.upgrade(alembic_config, "head")
    engine = create_engine(test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    """ORM session against the migrated test database.

    All rows are removed after each test so every test starts from an
    empty ``experiments`` table.
    """
    factory = sessionmaker(bind=migrated_engine)
    with factory() as session:
        yield session
    with migrated_engine.begin() as connection:
        connection.execute(sa.delete(Experiment))


@pytest.fixture()
def api_client(migrated_engine: Engine) -> Iterator[TestClient]:
    """HTTP client wired to the isolated test database.

    The app's session dependency is overridden so every request uses
    the throwaway database instead of the development database. The
    ``experiments`` table is emptied after each test.
    """
    factory = sessionmaker(bind=migrated_engine, autoflush=False, autocommit=False)

    def override_get_db_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        with migrated_engine.begin() as connection:
            connection.execute(sa.delete(Experiment))


@pytest.fixture()
async def shared_stack(migrated_engine: Engine, monkeypatch) -> AsyncIterator[tuple]:
    """REST and MCP wired to the *same* isolated test database.

    The FastAPI dependency and the MCP server's session factory both point
    at ``migrated_engine``, so a test can write through one interface and
    read through the other. Rows and overrides are cleaned up afterwards.
    """
    factory = sessionmaker(bind=migrated_engine, autoflush=False, autocommit=False)

    def override_get_db_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session
    monkeypatch.setattr(mcp_server_module, "SessionLocal", factory)
    try:
        with TestClient(app) as rest:
            async with Client(mcp_server_module.mcp, mode="legacy") as mcp:
                yield rest, mcp
    finally:
        app.dependency_overrides.clear()
        with migrated_engine.begin() as connection:
            connection.execute(sa.delete(Experiment))
