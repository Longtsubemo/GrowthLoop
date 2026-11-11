# Development guide

Everything here assumes Windows PowerShell. PowerShell 5.1 does not support
`&&` — run commands separately or chain with `;`. (`&&` inside npm scripts is
fine; npm runs them through cmd.)

## Prerequisites

| Tool | Version verified during initialization |
| --- | --- |
| Python | 3.12.4 — invoke as `py -3.12` (the system `python` is 3.13) |
| Node.js / npm | v22.19.0 / 11.6.4 |
| Docker Desktop | engine 29.8.1, Compose v5.5.1 |

## Database (PostgreSQL 17)

From the repository root:

```powershell
docker compose up -d     # start (Docker Desktop must be running)
docker compose down      # stop; add -v to also delete the data volume
```

Defaults (override via `.env`, see `.env.example`): user `postgres`, password
`postgres`, database `growthloop`, port 5432 on localhost.

## Backend

From `backend/`:

```powershell
py -3.12 -m venv .venv            # once
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"           # after dependency changes

# Set OWNER_PASSWORD in the root .env before using the dashboard/API.
# Set a unique secret of at least 16 characters; there is no default password.

uvicorn app.main:app --reload     # http://localhost:8000 — GET /health
pytest                            # all tests (DB tests need Postgres up)
pytest tests/test_health.py       # single file
pytest -k health                  # by keyword
```

If `Activate.ps1` is blocked by execution policy, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or invoke
`.venv\Scripts\python.exe -m pytest` directly.

## MCP server

From `backend/` with the venv active:

```powershell
python -m mcp_server.server       # stdio transport (for Claude Desktop)
growthloop-mcp                    # equivalent console script
```

Registers the seven experiment tools and speaks MCP over stdio. See
[MCP.md](MCP.md) for Claude Desktop configuration and troubleshooting;
`pytest tests/test_mcp_server.py` exercises all seven tools end-to-end
(in-memory JSON-RPC plus a real stdio subprocess).

## Frontend

From `frontend/`:

```powershell
npm install
npm run dev       # http://localhost:5173
npm run build     # type-check (tsc -b) + production build
npm run preview
npm run lint      # oxlint
```

The dashboard talks to the API through `src/lib/api.ts`, configured by
`VITE_API_BASE_URL` (default `http://localhost:8000`). Navigation uses a
dependency-free hash router (`src/lib/router.ts`):

| Route | Page |
| --- | --- |
| `#/` | Overview (counts + recent experiments) |
| `#/experiments` | List with status filter and pagination |
| `#/experiments/new` | Create form |
| `#/experiments/:id` | Detail, status change, result, delete |
| `#/experiments/:id/edit` | Edit form |

The backend allows the dev-server origin through `CORS_ORIGINS` (see
`.env.example`). Protected REST calls require an owner session and CSRF token;
the dashboard signs in with `OWNER_PASSWORD`. Remote MCP OAuth and its
`/mcp` endpoint are documented in [MCP.md](MCP.md).
The un-deployed Render and Neon preparation is documented in
[DEPLOYMENT.md](DEPLOYMENT.md).

### Browser tests (Playwright)

```powershell
npx playwright install chromium   # one-time browser download
npm run test:e2e                  # real API + throwaway database
```

The suite is intentionally end-to-end, not mocked:

1. `tests/global-setup.ts` runs `backend/scripts/reset_e2e_database.py`,
   which drops/recreates the `growthloop_e2e` database and applies Alembic
   migrations. The URL is derived from `DATABASE_URL` (or the `.env`
   files) with only the database name replaced. Both setup layers reject
   non-loopback hosts and any database name other than `growthloop_e2e`, so
   destructive test setup cannot connect to Neon or another remote database.
2. Playwright starts the real FastAPI backend on port **8377** (using
   `backend/.venv`) and Vite on port **5174**, with
   `VITE_API_BASE_URL=http://localhost:8377` and a random test-only owner
   password.
3. Tests create their data through the REST API (`tests/helpers.ts`) and
   run serially (`workers: 1`) because they share that database.

Requires local PostgreSQL (`docker compose up -d`) and the backend virtualenv.
If `DATABASE_URL` in the environment or `.env` points to a remote database,
the suite stops before connecting; set the process `DATABASE_URL` to the
local Compose URL for the test run. Development data is never touched; the
e2e database can be deleted at any time.

## Verification checklist

Run these before considering backend or frontend changes done:

1. `pytest` passes in `backend/`
2. `uvicorn app.main:app` starts and `GET /health` returns `{"status": "ok"}`
3. `npm run build` succeeds in `frontend/`
4. `npm run lint` succeeds in `frontend/`
5. `npm run test:e2e` passes in `frontend/` (PostgreSQL + backend venv)
