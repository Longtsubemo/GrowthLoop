# Database

## Local development

PostgreSQL 17 runs in Docker Compose (repository root):

```powershell
docker compose up -d    # start; Docker Desktop must be running
docker compose down     # stop; add -v to delete the data volume too
```

Connection defaults (override via `.env`, see `.env.example`):

| Setting | Value |
| --- | --- |
| Host | localhost |
| Port | 5432 |
| Database | growthloop |
| User / password | postgres / postgres |

## Connecting from the backend

The backend uses SQLAlchemy 2.x with the psycopg 3 driver. The connection
string comes from the `DATABASE_URL` environment variable (read in
`app/core/config.py`); the default matches the compose defaults above:

```
postgresql+psycopg://postgres:postgres@localhost:5432/growthloop
```

`app/db/session.py` builds the engine and session factory from settings.

## Schema & migrations

Alembic manages the schema (migrations live in `backend/alembic/versions/`;
the `experiments` table is the first and only table so far). From
`backend/`:

```powershell
python -m alembic upgrade head                        # apply pending migrations
python -m alembic downgrade -1                        # roll back one migration
python -m alembic current                             # show applied revision
python -m alembic revision --autogenerate -m "message"  # after model changes
```

The migration URL comes from application settings (`DATABASE_URL`); no URL
is stored in `alembic.ini`. After changing models in `app/models/`, always
generate a new migration instead of editing applied ones. The
`pytest` suite verifies that migrations upgrade and downgrade cleanly and
that the migrated schema matches the models.

## Tests

Database tests create a throwaway database on the same PostgreSQL server
(see `backend/tests/conftest.py`), apply migrations to it, and drop it when
the session ends — the development database is never modified by the test
suite. Tests are skipped with a hint if PostgreSQL is not reachable.

The frontend Playwright suite uses the same approach with a fixed
`growthloop_e2e` database: `backend/scripts/reset_e2e_database.py` drops,
recreates, and migrates it before the run. Only the database name differs
from `DATABASE_URL`, so it uses the same server and credentials.
