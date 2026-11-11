# GrowthLoop

GrowthLoop is a growth-experiment management application for startup founders
and growth teams. Experiments are created and updated by Claude through the
[Model Context Protocol](https://modelcontextprotocol.io) (MCP), and humans
review, edit, and operate on the same records in a React dashboard.

The application itself contains **no AI or LLM functionality**. It stores,
validates, and presents experiment data. Claude is an external client that
reaches the app through the local MCP server or the OAuth-protected remote
MCP endpoint; both call the same business logic as the REST API.

## Features

- **Experiment management** — create, list, filter, paginate, fetch, update,
  change lifecycle status, record results, and delete experiments.
- **Full lifecycle statuses** — `draft`, `planned`, `running`, `completed`,
  `paused`, `cancelled`.
- **Dashboard**
  - Overview page with total / active / running / completed counts and the
    six most recent experiments.
  - Searchable-by-status list with channel, budget, creation date,
    pagination, and loading / empty / error states.
  - Create and edit form with dynamic execution steps (add, remove,
    reorder) and inline validation.
  - Detail page with full data, timestamps, status transitions, result
    recording, and a confirmed delete.
- **One shared service layer** — the REST API and the MCP server call the
  same `backend/app/services/` functions, so Claude-side and dashboard-side
  changes always stay in sync.
- **Precision-safe budgets** — amounts are stored as PostgreSQL `NUMERIC(12,2)`
  and travel as decimal strings through both interfaces.
- **Owner access control** — the dashboard and REST API use an HttpOnly
  server-managed session with CSRF protection; remote MCP uses OAuth bearer
  tokens. Local stdio remains available for Claude Desktop.
- **Real end-to-end tests** — pytest against isolated PostgreSQL databases
  plus Playwright against the real FastAPI backend and database.

## Architecture

```
Claude Desktop -- MCP/stdio --> MCP server ----------------------+
                                                                  |
Claude connector -- OAuth/HTTP --> FastAPI MCP endpoint ---------+--> Shared services
                                                                  |   (backend/app/services/)
React dashboard -- session/CSRF --> FastAPI REST API -------------+          |
                                                                             v
                                                               PostgreSQL (SQLAlchemy)
```

| Layer | Technology |
| --- | --- |
| Frontend | React 19, Vite 8, TypeScript, Tailwind CSS v4, axios |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, psycopg 3 |
| MCP server | Python MCP SDK v2 (`mcp.server.mcpserver.MCPServer`), stdio and Streamable HTTP |
| Database | PostgreSQL 17 (Docker Compose locally), Alembic migrations |
| Tests | pytest + httpx, Playwright (`@playwright/test`) |

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for component boundaries
and design rules.

## Repository structure

```
growthloop/
├── backend/
│   ├── app/
│   │   ├── api/              # Thin FastAPI routers
│   │   ├── core/             # Settings loaded from env vars / .env
│   │   ├── db/               # Engine, session factory, declarative base
│   │   ├── models/           # SQLAlchemy Experiment model
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   └── services/         # Shared business logic (single source of truth)
│   ├── alembic/              # Migrations (env.py resolves DATABASE_URL)
│   ├── mcp_server/           # MCP server exposing the seven experiment tools
│   ├── scripts/              # E2E DB reset and stdio MCP helper (test-only)
│   ├── tests/                # pytest: API, model, migrations, MCP, cross-layer
│   ├── alembic.ini
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── components/       # Shared UI: form, badges, modal, states
│   │   ├── lib/              # Typed API client, hash router, formatters
│   │   └── pages/            # Overview, list, create, edit, detail
│   ├── tests/                # Playwright specs and helpers
│   ├── package.json
│   └── playwright.config.ts
├── docs/                     # Architecture, database, development, MCP guides
├── docker-compose.yml        # PostgreSQL 17
├── .env.example              # Documented environment variables
├── AGENTS.md                 # Repository working rules
└── README.md
```

## Prerequisites

| Tool | Requirement |
| --- | --- |
| Python | 3.12 — invoke as `py -3.12` (a system `python` may be 3.13) |
| Node.js / npm | Node.js 20+ and npm (verified with Node 22 / npm 11) |
| Docker Desktop | Required for the local PostgreSQL container |
| Git | Any recent version |

## Local setup (Windows PowerShell)

PowerShell 5.1 does not support `&&`; run commands separately or chain with
`;`. (`&&` inside npm scripts is fine because npm uses `cmd`.)

### 1. Clone and enter the repository

```powershell
git clone https://github.com/Longtsubemo/GrowthLoop.git
cd GrowthLoop
```

### 2. Configure the environment (optional)

The backend defaults match `docker-compose.yml`, so the app runs with no
`.env` file. To override anything, copy the example file:

```powershell
Copy-Item .env.example .env
```

Never commit `.env` — it is gitignored. See
[Environment configuration](#environment-configuration) for the variables.

### 3. Start PostgreSQL

Docker Desktop must be running.

```powershell
docker compose up -d     # start PostgreSQL 17 on localhost:5432
docker compose ps        # check the health status
```

Stop it later with `docker compose down` (add `-v` to also delete the data
volume). Defaults: user `postgres`, password `postgres`, database
`growthloop`, port `5432`.

### 4. Backend

From `backend/`:

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

The API runs at <http://localhost:8000>. Verify it with
`GET http://localhost:8000/health` → `{"status":"ok"}`. Interactive API docs
are at <http://localhost:8000/docs>.

Set a unique `OWNER_PASSWORD` in the root `.env` before opening the dashboard;
there is no default password. The same owner password approves remote MCP
authorization. Keep it private and use at least 16 characters. `MCP_ISSUER_URL`
defaults to `http://localhost:8000` for local development.

If `Activate.ps1` is blocked by the execution policy, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or call
`.venv\Scripts\python.exe` directly.

### 5. Frontend

In a second terminal, from `frontend/`:

```powershell
cd frontend
npm install
npm run dev
```

The dashboard runs at <http://localhost:5173>. It talks to
`http://localhost:8000` by default; set `VITE_API_BASE_URL` to point it at a
different backend.

### 6. MCP server (for Claude)

The MCP server is started automatically by an MCP client; you do not run it
alongside the dashboard. To launch it manually from `backend/` with the venv
active:

```powershell
python -m mcp_server.server    # stdio transport — waits for an MCP client
```

Claude Desktop configuration, the absolute venv path, and troubleshooting
are documented in [`docs/MCP.md`](docs/MCP.md).

## Environment configuration

Most variables are optional locally; the defaults below match
`docker-compose.yml` and the Vite dev server. `OWNER_PASSWORD` must be set to
use the dashboard or approve remote MCP access. Configuration is read from the
process environment and then from `.env` in the working directory or the
repository root (so one root `.env` works when the backend runs from
`backend/`).

| Variable | Default | Used by | Purpose |
| --- | --- | --- | --- |
| `APP_ENV` | `development` | Backend | `development` preserves local defaults; `production` requires explicit hosted database and browser-origin settings |
| `DEBUG` | `false` | Backend | Debug mode is opt-in for local development; production rejects `true` |
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/growthloop` | Backend, Alembic, MCP | PostgreSQL connection URL. Standard `postgresql://` and `postgres://` provider URLs are parsed and switched to psycopg 3 without dropping query parameters |
| `OWNER_PASSWORD` | none | Backend | Required owner password for the dashboard, REST API session, and remote MCP consent; set a unique secret of 16–1024 characters |
| `OWNER_SESSION_TTL_SECONDS` | `28800` | Backend | Owner session lifetime, from 5 minutes to 24 hours |
| `MCP_ISSUER_URL` | `http://localhost:8000` | Backend, MCP | Exact API base URL used as the remote MCP OAuth issuer and resource origin |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Backend | Comma-separated browser origins allowed to call the API |
| `MCP_ALLOWED_HOSTS` | local API hostnames | Backend, MCP | Exact Host-header hostnames accepted by the app and MCP transport |
| `MCP_ALLOWED_ORIGINS` | local dashboard origins | Backend, MCP | Exact browser origins accepted by MCP transport checks |
| `DB_POOL_SIZE` | `2` | Backend | Number of SQLAlchemy connections retained per process |
| `DB_MAX_OVERFLOW` | `0` | Backend | Temporary connections above the pool size |
| `DB_POOL_TIMEOUT_SECONDS` | `5` | Backend | Maximum wait for a pooled connection |
| `DB_POOL_RECYCLE_SECONDS` | `300` | Backend | Recycle interval for pooled connections |
| `DB_CONNECT_TIMEOUT_SECONDS` | `10` | Backend | Maximum wait for a new PostgreSQL connection |
| `POSTGRES_USER` | `postgres` | Docker Compose | PostgreSQL user |
| `POSTGRES_PASSWORD` | `postgres` | Docker Compose | PostgreSQL password |
| `POSTGRES_DB` | `growthloop` | Docker Compose | Database name |
| `POSTGRES_PORT` | `5432` | Docker Compose | Host port for PostgreSQL |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Frontend | Base URL of the REST API |

`.env.example` documents local defaults and commented production examples.
For production, set `APP_ENV=production`, `DEBUG=false`, a strong unique
`OWNER_PASSWORD`, hosted `DATABASE_URL`, exact public API `MCP_ISSUER_URL`,
exact API hostname in `MCP_ALLOWED_HOSTS`, and the dashboard's exact HTTPS
origin in `CORS_ORIGINS`. Use HTTPS and exact MCP origins when browser MCP
clients need them. Production configuration rejects missing/local database
URLs and local or non-HTTPS origins. Keep real credentials in the host's secret
environment store; never commit them. Remote MCP authentication is implemented
but has not been deployed or verified against a live public Claude connector.

## Deployment preparation

[`render.yaml`](render.yaml) describes a Render Free Web Service and Static
Site on `dev`, with the frontend pointed at the backend and no automatic
redeploys. [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) gives the manual Neon and
Render steps, environment variables, migration procedure, smoke checks, and
free-tier limits. The existing Neon `my-first-project` database is prepared
for the app; no Render services have been created. Free hosting has cold
starts, finite quotas, and limited backup/restore guarantees; this is demo
preparation rather than production-grade hosting.

## Database and migrations

Alembic reads the URL from application settings (`DATABASE_URL`); no URL is
stored in `alembic.ini`. From `backend/` with the venv active:

```powershell
alembic upgrade head                              # apply pending migrations
alembic current                                   # show applied revision
alembic downgrade -1                              # roll back one migration
alembic revision --autogenerate -m "message"      # after changing models
```

The schema currently has one table, `experiments`, with a non-native status
enum (VARCHAR + CHECK constraint), JSONB execution steps, a `NUMERIC(12,2)`
budget, and timezone-aware timestamps. See
[`docs/DATABASE.md`](docs/DATABASE.md).

## REST API

Base URL: `http://localhost:8000`. All endpoints are under `/api/v1`.

| Method | Path | Description | Success |
| --- | --- | --- | --- |
| `GET` | `/health` | Liveness check | `200` |
| `GET` | `/health/ready` | Readiness check; runs `SELECT 1` against PostgreSQL | `200` or `503` |
| `POST` | `/api/v1/experiments` | Create an experiment | `201` |
| `GET` | `/api/v1/experiments` | List experiments, newest first. Query: `status`, `limit` (1–100, default 20), `offset` (default 0) | `200` |
| `GET` | `/api/v1/experiments/{experiment_id}` | Fetch one experiment by UUID | `200` |
| `PATCH` | `/api/v1/experiments/{experiment_id}` | Partially update fields; omitted fields are unchanged | `200` |
| `PATCH` | `/api/v1/experiments/{experiment_id}/status` | Change lifecycle status | `200` |
| `PATCH` | `/api/v1/experiments/{experiment_id}/result` | Record the actual result | `200` |
| `DELETE` | `/api/v1/experiments/{experiment_id}` | Permanently delete an experiment | `204` |

Request schemas are strict (`extra="forbid"`); `id`, `created_at`, and
`updated_at` are never client-writable. Unknown IDs return `404`. Unknown
status values and invalid fields return `422`.

Experiment fields: `id`, `title`, `hypothesis`, `target_audience`, `channel`,
`budget_amount`, `currency_code`, `status`, `execution_steps`,
`success_metric`, `actual_result`, `created_at`, `updated_at`.

`GET /docs` serves the interactive OpenAPI documentation and
`GET /openapi.json` the raw schema.

## MCP server and tools

The MCP server lives in `backend/mcp_server/` and speaks MCP over **stdio**.
It calls only the shared services in `backend/app/services/` — it never opens
its own database path or duplicates business rules. It uses the MCP Python
SDK v2 (`from mcp.server.mcpserver import MCPServer`).

The seven tools:

| Tool | Inputs | Notes |
| --- | --- | --- |
| `create_experiment` | `title`, `hypothesis`, `target_audience`, `channel`, `success_metric` (required); `budget_amount`, `currency_code` (default `INR`), `status` (default `draft`), `execution_steps`, `actual_result` | Persists a new experiment and returns the full record |
| `list_experiments` | `status` (optional), `limit` (1–100, default 20), `offset` (default 0) | Newest first; returns `items`, `total`, `limit`, `offset` |
| `get_experiment` | `experiment_id` (UUID) | Returns one record |
| `update_experiment` | `experiment_id` plus any subset of fields | Omitted fields are unchanged; explicit `null` clears `budget_amount` / `actual_result`; use the status tool for status |
| `update_experiment_status` | `experiment_id`, `status` | `draft`, `planned`, `running`, `completed`, `paused`, `cancelled` |
| `record_experiment_result` | `experiment_id`, `actual_result` | Records the outcome |
| `delete_experiment` | `experiment_id` | **Destructive** — permanently removes the record |

Each tool validates input with the shared Pydantic schemas, returns the
experiment serialized exactly like the REST API, and translates domain and
database errors into clean tool errors without leaking SQL, credentials, or
stack traces.

**Client configuration:** see [`docs/MCP.md`](docs/MCP.md) for the Claude
Desktop `mcpServers` entry, the absolute venv Python path, verification
steps, and troubleshooting.

## Tests

### Backend (pytest)

From `backend/` with the venv active and PostgreSQL running:

```powershell
pytest                                    # full suite
pytest tests/test_api_experiments.py      # one file
pytest -k health                          # by keyword
```

Database-backed tests create a throwaway `growthloop_test_<hex>` database,
apply migrations, and drop it afterwards; the development database is never
modified. Tests are skipped with a hint if PostgreSQL is unreachable.

The suite covers the API, model, migrations, all seven MCP tools (in-memory
JSON-RPC and a real stdio subprocess), cross-layer MCP ↔ REST parity,
persistence across real FastAPI restarts and MCP reconnects, database-outage
handling, duplicate semantics, and concurrent updates.

### Frontend (Playwright)

From `frontend/`:

```powershell
npx playwright install chromium   # one-time browser download
npm run test:e2e                  # real API + real database + real MCP stdio
npm run build                     # tsc -b + vite build
npm run lint                      # oxlint
```

The Playwright suite resets the dedicated `growthloop_e2e` PostgreSQL
database, starts FastAPI on port `8377`, and Vite on port `5174`. It runs
serially (`workers: 1`) because the specs share that database. Development
data is never touched.

## Current limitations

- **Single owner, no multi-tenancy.** All records belong to one implicit
  workspace. The dashboard and REST API use one configured owner password;
  the remote MCP OAuth flow grants that same owner's access.
- **Authentication state is in process memory.** Restarting the API invalidates
  sessions, OAuth clients, and tokens. Run a single application worker; multiple
  workers do not share authentication state. A persistent shared store is needed
  before horizontally scaled production use.
- **Duplicate creates are not idempotent.** Two identical `create_experiment`
  calls produce two separate records by design. Retries must be handled by
  the client.
- **Concurrent updates are last-write-wins.** There is no optimistic locking;
  simultaneous edits settle on the last committed write without conflict
  detection.
- **Remote MCP is not publicly deployed.** The app exposes `/mcp` over
  Streamable HTTP with OAuth, but deployment and live connector verification
  have not been done. Local stdio remains available for Claude Desktop.
- **stdio is a trusted local process.** It retains the existing unauthenticated
  local transport and should only be launched by a trusted MCP client.
- **Deployment is not live.** A Render Blueprint is prepared, but no Render
  service or Neon project has been created and no public connector has been
  tested. See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Security guidance

- Never commit `.env` files, credentials, tokens, database dumps, or virtual
  environments. `.gitignore` excludes them; `.env.example` is the only
  environment file that belongs in Git.
- Change the default PostgreSQL credentials for anything other than local
  development, and keep PostgreSQL bound to localhost.
- Keep `OWNER_PASSWORD`, database credentials, session cookies, and OAuth
  tokens private. Use HTTPS for hosted dashboard and MCP traffic.
- Transport Host/Origin checks are separate from authentication. The dashboard
  uses an HttpOnly session cookie plus CSRF token; remote MCP requires OAuth
  bearer tokens.
- No AI/LLM API keys belong in this codebase. Claude reaches the application
  only through MCP, and the MCP server needs no LLM credentials.
- Database errors are translated into controlled client errors; server-side
  logs may contain operational detail and should not be exposed publicly.

## Git workflow

- **`main`** is the stable branch. It should always be in a verified state.
- **`dev`** is the ongoing development branch. Day-to-day work happens here.
- Do not create additional feature branches. Do not force-push. Do not merge
  `dev` into `main` without an explicit release decision.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, boundaries, and design rules
- [`docs/DATABASE.md`](docs/DATABASE.md) — PostgreSQL setup, schema, and migrations
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — Render and Neon free-tier deployment preparation
- [`docs/MCP.md`](docs/MCP.md) — MCP server and Claude Desktop configuration
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — full development and verification guide
- [`frontend/README.md`](frontend/README.md) — dashboard structure and Playwright setup
- [`AGENTS.md`](AGENTS.md) — repository working rules
