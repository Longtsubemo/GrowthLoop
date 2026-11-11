# Architecture

GrowthLoop has three components, and all three meet in the shared business
logic:

```
Claude Desktop
      |  MCP (stdio)
      v
Python MCP server (backend/mcp_server/)
      |
      v
Shared business logic (backend/app/services/)
      |
      +--> FastAPI REST API (backend/app/api/) --> React dashboard (frontend/)
      |
      v
PostgreSQL (SQLAlchemy: backend/app/db/, backend/app/models/)
```

## Components

### Frontend — `frontend/`

React 19 + Vite 8 + TypeScript + Tailwind CSS v4. Talks to the FastAPI REST
API over HTTP (axios client in `src/lib/api.ts`, base URL from
`VITE_API_BASE_URL`). The single place where humans review and edit
everything.

Structure:

- `src/App.tsx` maps routes to pages inside the shared `AppLayout` shell
  (sidebar, header, responsive mobile navigation).
- `src/lib/` — typed API client, hash router, display formatters, and a
  small async-data hook. Budget amounts stay decimal strings end-to-end;
  they are parsed only for display.
- `src/pages/` — Overview, experiment list, create, edit, and detail.
- `src/components/` — reusable form, status badge, pagination, modal,
  confirmation dialog, and loading/empty/error states.
- `tests/` — Playwright specs. They run against the real backend and a
  dedicated `growthloop_e2e` PostgreSQL database, so they verify the full
  browser → CORS → REST → service → database path rather than mocks.

The dashboard never talks to PostgreSQL or MCP directly: every read and
write goes through the same REST endpoints (and therefore the same shared
services) that the MCP server uses.

### Backend — `backend/app/`

FastAPI REST API. Routers in `app/api/` stay thin and delegate to services in
`app/services/`. Persistence: SQLAlchemy models in `app/models/`, engine and
session factory in `app/db/session.py`, PostgreSQL underneath.

### MCP server — `backend/mcp_server/`

Python MCP SDK v2 (`from mcp.server.mcpserver import MCPServer`). Exposes
the seven experiment tools (`create_experiment`, `list_experiments`,
`get_experiment`, `update_experiment`, `update_experiment_status`,
`record_experiment_result`, `delete_experiment`) over stdio; each tool
calls the same `app/services` logic used by the REST API. It must never
open its own database session path or duplicate business rules — that
symmetry is what keeps Claude-side and dashboard-side changes
synchronized. See [MCP.md](MCP.md) for Claude Desktop setup.

## Rules

- No AI/LLM functionality and no LLM API keys anywhere in GrowthLoop. Claude
  is an external client that reaches the application only through MCP.
- Everything an MCP tool can change must be visible and editable in the
  dashboard.
- Configuration comes from environment variables (`.env` /
  `.env.example`); never hardcode credentials.

## Package naming

The MCP server package is `backend/mcp_server/`, not `backend/mcp/`: the
Python MCP SDK's import name is `mcp`, so a local `mcp` package would shadow
it and break `import mcp`.

## Local vs hosted MCP

Today the server runs locally over stdio, launched as
`python -m mcp_server.server` (or the `growthloop-mcp` console script). The
SDK also supports streamable HTTP transports; when a publicly accessible MCP
endpoint is needed, add the transport without touching tool implementations —
tools depend only on the shared services.
