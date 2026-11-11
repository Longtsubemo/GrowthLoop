# GrowthLoop

GrowthLoop is a growth-experiment management application for startup founders
and growth teams. Experiments are created and updated by Claude through the
[Model Context Protocol](https://modelcontextprotocol.io) (MCP), and humans
review, edit, and operate on the same records in a React dashboard.

The application itself contains **no AI or LLM functionality**. It stores,
validates, and presents experiment data. Claude is an external client that
reaches the app only through the local MCP server, which calls the same
business logic as the REST API.

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
- **Real end-to-end tests** — pytest against a throwaway PostgreSQL database
  plus Playwright against the real FastAPI backend, real database, and real
  MCP stdio process.

## Architecture

```
Claude Desktop
      |  MCP over stdio
      v
Python MCP server  (backend/mcp_server/)
      |
      v
Shared business logic  (backend/app/services/)
      |
      +--> FastAPI REST API  (backend/app/api/)  -->  React dashboard (frontend/)
      |
      v
PostgreSQL  (SQLAlchemy: backend/app/db/, backend/app/models/)
```

| Layer | Technology |
| --- | --- |
| Frontend | React 19, Vite 8, TypeScript, Tailwind CSS v4, axios |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, psycopg 3 |
| MCP server | Python MCP SDK v2 (`mcp.server.mcpserver.MCPServer`), stdio transport |
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

All variables are optional locally; the defaults below match
`docker-compose.yml` and the Vite dev server. Configuration is read from the
process environment and then from `.env` in the working directory or the
repository root (so one root `.env` works when the backend runs from
`backend/`).

| Variable | Default | Used by | Purpose |
| --- | --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/growthloop` | Backend, Alembic, MCP | SQLAlchemy connection string (psycopg 3 driver) |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Backend | Comma-separated browser origins allowed to call the API |
| `POSTGRES_USER` | `postgres` | Docker Compose | PostgreSQL user |
| `POSTGRES_PASSWORD` | `postgres` | Docker Compose | PostgreSQL password |
| `POSTGRES_DB` | `growthloop` | Docker Compose | Database name |
| `POSTGRES_PORT` | `5432` | Docker Compose | Host port for PostgreSQL |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Frontend | Base URL of the REST API |

`.env.example` documents the same variables. Real credentials must never be
committed.

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

### Current verified results (Phase 5A)

Verified on 2026-11-11:

| Check | Result |
| --- | --- |
| `pytest` (full backend suite) | **155 passed** |
| `npm run test:e2e` (full Playwright suite) | **25 passed** |
| `npm run build` | passed |
| `npm run lint` | passed |

## Current limitations

- **No authentication or multi-tenancy.** The API is unauthenticated and all
  records belong to one implicit workspace. Do not expose it publicly.
- **Duplicate creates are not idempotent.** Two identical `create_experiment`
  calls produce two separate records by design. Retries must be handled by
  the client.
- **Concurrent updates are last-write-wins.** There is no optimistic locking;
  simultaneous edits settle on the last committed write without conflict
  detection.
- **MCP runs locally over stdio only.** The SDK supports streamable HTTP, but
  no hosted/remote MCP endpoint is implemented.
- **Deployment is not set up.** Vercel/Render are planned, not configured.
  This repository contains no deployment manifests or hosted configuration.

## Security guidance

- Never commit `.env` files, credentials, tokens, database dumps, or virtual
  environments. `.gitignore` excludes them; `.env.example` is the only
  environment file that belongs in Git.
- Change the default PostgreSQL credentials for anything other than local
  development, and keep PostgreSQL bound to localhost.
- Because there is no authentication, treat the API as a local-development
  tool. Do not deploy or expose it without adding authentication and
  authorization first.
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
- [`docs/MCP.md`](docs/MCP.md) — MCP server and Claude Desktop configuration
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — full development and verification guide
- [`frontend/README.md`](frontend/README.md) — dashboard structure and Playwright setup
- [`AGENTS.md`](AGENTS.md) — repository working rules
