"""Create or reset the throwaway database used by the Playwright e2e suite.

The frontend e2e tests (``frontend/tests``) run the real FastAPI backend
against an isolated PostgreSQL database so they never touch development
data — the same strategy as ``backend/tests/conftest.py``. This script
drops and recreates that database and applies all migrations.

It is invoked by ``frontend/tests/global-setup.ts`` as:

    python scripts/reset_e2e_database.py <e2e-database-url>

The URL is passed in by the TypeScript side (which derives it from
``DATABASE_URL`` in the environment or ``.env`` files), so both sides use
a single source of truth for where the e2e database lives.

Exits non-zero with a clear message when PostgreSQL is not reachable.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
# Allow `app.*` imports (used by alembic's env.py) even when the script
# is launched outside the editable-install venv.
sys.path.insert(0, str(BACKEND_DIR))

import sqlalchemy as sa  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: reset_e2e_database.py <e2e-database-url>", file=sys.stderr)
        return 2
    e2e_url = make_url(sys.argv[1])
    server_url = e2e_url.set(database="postgres")

    engine = create_engine(server_url)
    try:
        with engine.connect():
            pass
    except sa.exc.OperationalError:
        engine.dispose()
        print(
            "PostgreSQL is not reachable — start it with `docker compose up -d`.",
            file=sys.stderr,
        )
        return 1

    database = e2e_url.database
    with engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(
            sa.text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        )
        connection.execute(sa.text(f'CREATE DATABASE "{database}"'))
    engine.dispose()

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option(
        "sqlalchemy.url", e2e_url.render_as_string(hide_password=False)
    )
    command.upgrade(config, "head")

    print(f"e2e database ready: {database} on {server_url.render_as_string(hide_password=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
