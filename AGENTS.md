# AGENTS.md

GrowthLoop: a growth experiment management SaaS. Claude (an external client)
manages experiments through MCP; humans review and edit everything in a React
dashboard. The application itself only stores, validates, and presents data.

## Project phase

Phase 4 is complete: on top of the Phase 3 backend (Experiment model,
migrations, Pydantic schemas, shared service layer, `/api/v1/experiments`
REST endpoints, and the MCP server with exactly seven experiment tools),
the human-facing dashboard is implemented. It has an Overview page,
experiment list with filtering/pagination, create/edit/detail pages,
status changes, result recording, and confirmed deletes, plus a Playwright
suite that drives the real backend and database. Authentication and
multi-tenancy are intentionally **not** implemented. Do not implement the
next feature without explicit user approval.

## Non-negotiable constraints

- No AI/LLM functionality and no LLM API keys anywhere in this codebase. Never
  create or request one. Claude reaches the app only through MCP.
- The MCP server (`backend/mcp_server/`) must call the shared services in
  `backend/app/services/`; it must never open its own DB path or duplicate
  business logic. REST routers in `backend/app/api/` stay thin and delegate to
  the same services.
- Everything an MCP tool can change must be reviewable/editable in the
  dashboard.
- Configuration comes from env vars (`.env`, modeled by `.env.example`);
  never hardcode credentials. Do not deploy anything unless asked
  (Vercel/Render are planned, not set up).

## Git rules (user-mandated)

- Persistent `dev` branch only; keep `main` stable. No feature branches.
- No merges into `main`. Do not commit unless explicitly asked. Never push.

## Layout

- `backend/app/` — FastAPI app: `api/` routers, `core/` settings, `db/`
  engine+session+declarative base, `models/` SQLAlchemy, `schemas/` Pydantic,
  `services/` shared business logic (single source of truth for both API and
  MCP).
- `backend/alembic/` — migrations; `env.py` resolves the DB URL from app
  settings and imports `app.models` for autogenerate (`alembic.ini` stores
  no URL).
- `backend/mcp_server/` — MCP server: seven experiment tools over stdio
  (`server.py`), calling only the shared services. Named `mcp_server`
  because the SDK's import name is `mcp` — never create a local `mcp`
  package or it shadows the SDK.
- `backend/tests/` — pytest: FastAPI TestClient tests, MCP client/server
  integration tests (in-memory + stdio), and DB-level tests that use a
  throwaway database (skipped if PostgreSQL is not running).
- `frontend/` — React 19 + Vite 8 + TypeScript + Tailwind v4 dashboard.
  `src/lib/api.ts` is the only HTTP client (typed REST calls);
  `src/lib/router.ts` is a dependency-free hash router; pages live in
  `src/pages/`, shared UI in `src/components/`. Playwright specs are in
  `tests/` and run against the real API and a dedicated `growthloop_e2e`
  PostgreSQL database.

## Commands (Windows PowerShell)

PowerShell 5.1 has no `&&` — use `;` or separate calls. (`&&` inside npm
scripts is fine; npm uses cmd.) Venv activation is
`.venv\Scripts\Activate.ps1`.

Backend — from `backend/`:

```powershell
py -3.12 -m venv .venv            # system "python" is 3.13; project is 3.12
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest                           # all tests (DB tests need Postgres up)
pytest tests/test_health.py      # single file
alembic upgrade head             # apply pending migrations
alembic revision --autogenerate -m "msg"  # after changing models
uvicorn app.main:app --reload    # http://localhost:8000 — GET /health
python -m mcp_server.server      # MCP over stdio (also: growthloop-mcp)
```

Database — from repo root; Docker Desktop must be running (start it if not):

```powershell
docker compose up -d             # postgres:17, defaults postgres/postgres/growthloop @ localhost:5432
docker compose down              # add -v to wipe the data volume
```

Frontend — from `frontend/`:

```powershell
npm run dev       # http://localhost:5173
npm run build     # tsc -b + vite build — the done-gate for frontend changes
npm run lint      # oxlint (this repo uses oxlint, not eslint)
npx playwright install chromium  # one-time, required before e2e
npm run test:e2e  # real API + DB; requires Postgres and backend/.venv
```

The e2e suite starts its own FastAPI backend on port 8377 and Vite dev
server on port 5174, resetting/migrating `growthloop_e2e` first. It never
touches the development database and runs serially.

## Gotchas

- Use `py -3.12` for anything Python; the default `python` is 3.13.
- MCP SDK is v2: `from mcp.server.mcpserver import MCPServer`. The v1
  `FastMCP` shown in most older docs no longer exists.
- Tailwind v4 has no `tailwind.config.js`; config is CSS-first
  (`@import "tailwindcss"` in `src/index.css`, `@tailwindcss/vite` plugin in
  `vite.config.ts`).
- Backend settings read `.env` then `../.env`, so one root `.env` works when
  running from `backend/`. Defaults match compose, so it also runs with no
  `.env` at all.
- Backend must run from `backend/` (or use the venv's installed packages) so
  `app.*` and `mcp_server.*` resolve.

## Before finishing any change

`pytest` green in `backend/`; `npm run build`, `npm run lint`, and
`npm run test:e2e` green in `frontend/` (e2e needs PostgreSQL and the
backend venv). Don't claim a check passed without running it. See
`docs/DEVELOPMENT.md` for the full guide.
