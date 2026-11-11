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

## Hosted PostgreSQL

For production, set `APP_ENV=production`, `DEBUG=false`, an explicit managed
database URL, and the dashboard's exact HTTPS origin in `CORS_ORIGINS`. The
application rejects missing production database/origin settings, localhost
database hosts, and non-HTTPS or local browser origins. Store credentials in
the hosting provider's secret environment settings; do not put real URLs in
`.env.example` or source control.

Managed providers often supply a `postgresql://` (or legacy `postgres://`)
URL. Both the application engine and Alembic parse that value as a SQLAlchemy
URL and select the psycopg 3 driver (`postgresql+psycopg`) while preserving
encoded credentials and query parameters such as `sslmode=require`. A URL
already using `postgresql+psycopg://` is kept as configured. Do not remove the
provider's SSL options. `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`,
`DB_POOL_RECYCLE_SECONDS`, and `DB_CONNECT_TIMEOUT_SECONDS` configure the
small per-process pool; the defaults are 2 retained connections, no overflow,
and bounded connection waits.

For the prepared Render setup, Neon supplies the production URL. Copy the
pooled connection string for the runtime application, retain Neon's SSL
parameters, and use the direct owner connection only when running migrations
manually. The Render configuration uses one process, a pool size of one, and
zero overflow connections. The existing Neon setup uses the least-privilege
`growthloop_app` role for runtime CRUD and keeps `neondb_owner` separate for
migrations. See [DEPLOYMENT.md](DEPLOYMENT.md) for the two-role configuration
and applying migrations without running them at every application startup.

`GET /health` is a liveness check and does not depend on PostgreSQL.
`GET /health/ready` runs `SELECT 1` and returns `503` with a generic message
when PostgreSQL cannot be reached; it never returns connection details.

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
