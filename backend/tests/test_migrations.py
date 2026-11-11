"""Tests for Alembic migrations."""

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine

import app.models  # noqa: F401 — registers models on Base.metadata
from app.db.base import Base

EXPECTED_COLUMNS = {
    "id",
    "title",
    "hypothesis",
    "target_audience",
    "channel",
    "budget_amount",
    "currency_code",
    "status",
    "execution_steps",
    "success_metric",
    "actual_result",
    "created_at",
    "updated_at",
}

NULLABLE_COLUMNS = {"budget_amount", "actual_result"}


def test_upgrade_and_downgrade_cycle(
    alembic_config: Config, migrated_engine: Engine
) -> None:
    assert "experiments" in _table_names(migrated_engine)

    command.downgrade(alembic_config, "base")
    assert "experiments" not in _table_names(migrated_engine)

    command.upgrade(alembic_config, "head")
    table_names = _table_names(migrated_engine)
    assert "experiments" in table_names
    assert "alembic_version" in table_names


def test_schema_matches_model_metadata(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True}
        )
        diff = compare_metadata(context, Base.metadata)

    assert diff == [], f"database schema drifted from models: {diff}"


def test_experiments_table_structure(migrated_engine: Engine) -> None:
    inspector = sa.inspect(migrated_engine)
    columns = {
        column["name"]: column for column in inspector.get_columns("experiments")
    }

    assert set(columns) == EXPECTED_COLUMNS
    assert NULLABLE_COLUMNS <= {
        name for name, column in columns.items() if column["nullable"]
    }
    assert not (EXPECTED_COLUMNS - NULLABLE_COLUMNS) & {
        name for name, column in columns.items() if column["nullable"]
    }

    assert isinstance(columns["id"]["type"], sa.UUID)
    assert isinstance(columns["execution_steps"]["type"], postgresql.JSONB)
    assert isinstance(columns["budget_amount"]["type"], sa.Numeric)

    check_constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("experiments")
    }
    assert "experiment_status" in check_constraints
    assert "ck_experiments_currency_code_length" in check_constraints

    indexes = {index["name"] for index in inspector.get_indexes("experiments")}
    assert {"ix_experiments_status", "ix_experiments_created_at"} <= indexes


def _table_names(engine: Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())
