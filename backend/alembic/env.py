"""Alembic migration environment.

The database URL is resolved from, in order:

1. ``sqlalchemy.url`` on the Alembic config (set programmatically by the
   test suite or overridden on the command line),
2. application settings (``DATABASE_URL`` / ``.env`` — see
   ``app.core.config``).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401 — registers models on Base.metadata
from app.core.config import get_settings
from app.db.base import Base
from app.db.url import normalize_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

raw_database_url = (
    config.get_main_option("sqlalchemy.url") or get_settings().database_url
)
database_url = normalize_database_url(raw_database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of against a live connection."""
    context.configure(
        # Offline SQL generation needs the dialect URL but no credentials.
        url=database_url.render_as_string(hide_password=True),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    settings = get_settings()
    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
        hide_parameters=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
