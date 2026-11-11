# MCP server

GrowthLoop exposes its experiment operations to Claude through a local
MCP server that speaks the Model Context Protocol over stdio
(`backend/mcp_server/`). The server is a plain Python process — no HTTP
server, no Claude API key, and no AI functionality of its own. It calls
the same shared services (`backend/app/services/experiment_service.py`)
as the REST API, so Claude and the dashboard always operate on the same
experiment records in PostgreSQL.

The server uses the Python MCP SDK v2 (`from mcp.server.mcpserver import
MCPServer`; the v1 `FastMCP` class no longer exists).

## The seven tools

| Tool | Inputs | Notes |
| --- | --- | --- |
| `create_experiment` | `title`, `hypothesis`, `target_audience`, `channel`, `success_metric` (required); `budget_amount`, `currency_code` (default `INR`), `status` (default `draft`), `execution_steps`, `actual_result` (optional) | Persists a new experiment; returns the full stored record. |
| `list_experiments` | `status` (optional), `limit` (1–100, default 20), `offset` (default 0) | Newest first, returns `items`, `total`, `limit`, `offset`. |
| `get_experiment` | `experiment_id` (UUID) | |
| `update_experiment` | `experiment_id` plus any subset of the experiment fields | Omitted fields are unchanged; explicit `null` clears `budget_amount`/`actual_result`. Use `update_experiment_status` for status. |
| `update_experiment_status` | `experiment_id`, `status` | `draft`, `planned`, `running`, `completed`, `paused`, `cancelled`. |
| `record_experiment_result` | `experiment_id`, `actual_result` | |
| `delete_experiment` | `experiment_id` | **Destructive** — permanently removes the experiment; cannot be undone. |

Every tool validates its input (against the shared Pydantic schemas in
`backend/app/schemas/experiment.py`) before touching the database,
reports unknown ids and invalid values as clean tool errors, and returns
the experiment serialized exactly like the REST API returns it.

## Prerequisites

1. **PostgreSQL running** (repository root):

   ```powershell
   docker compose up -d
   ```

2. **Backend venv set up** (from `backend/`):

   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -e ".[dev]"
   ```

3. **Schema applied** (from `backend/`, venv active):

   ```powershell
   alembic upgrade head
   ```

Connection settings come from `DATABASE_URL` (defaults match the
compose service: `postgres:postgres@localhost:5432/growthloop`, see
[docs/DATABASE.md](DATABASE.md)). A root `.env` or `backend/.env` is
picked up automatically; environment variables always win.

## Locating the virtual environment executable

Claude Desktop needs the absolute path of the venv's Python. With the
repository at `C:\Users\<you>\Desktop\projects\growthloop` it is:

```
C:\Users\<you>\Desktop\projects\growthloop\backend\.venv\Scripts\python.exe
```

Verify it exists:

```powershell
Test-Path ..\backend\.venv\Scripts\python.exe   # from the repo root
```

## Configuring Claude Desktop (Windows)

Edit **your own** Claude Desktop config file — this project never
modifies it automatically:

```
%APPDATA%\Claude\claude_desktop_config.json
```

(Quick way to open it from PowerShell:
`notepad "$env:APPDATA\Claude\claude_desktop_config.json"`.)

Add a `growthloop` entry to `mcpServers` — note the doubled
backslashes in JSON string literals, and use your actual user name:

```json
{
  "mcpServers": {
    "growthloop": {
      "command": "C:\\Users\\<you>\\Desktop\\projects\\growthloop\\backend\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server.server"],
      "cwd": "C:\\Users\\<you>\\Desktop\\projects\\growthloop\\backend"
    }
  }
}
```

Notes:

- `cwd` must be the `backend/` directory so the `app.*` and
  `mcp_server.*` packages resolve.
- The editable install also provides a `growthloop-mcp` console script;
  running `python -m mcp_server.server` (as above) avoids any PATH or
  re-install concerns. If you prefer the script, point `command` at
  `...\backend\.venv\Scripts\growthloop-mcp.exe` and drop `args`.
- Optional: add `"env": { "DATABASE_URL": "postgresql+psycopg://postgres:postgres@localhost:5432/growthloop" }`
  to override the database explicitly.
- Restart Claude Desktop completely (quit from the tray, not just the
  window) after saving the config.

## Verifying the seven tools

**With Claude Desktop:** after restarting, the `growthloop` server
appears under Settings → Connectors / Developer tools (name varies by
Claude version). Ask Claude to *"list my growth experiments"* — it
should call `list_experiments` and report an empty list. Then try
*"create a growth experiment titled 'Referral bonus' testing whether a
₹500 referral bonus increases invites, target audience: existing users,
channel: referral_program, success metric: invites per user"* and
*"show my experiments"*.

**Without Claude Desktop** (raw JSON-RPC over stdio, from `backend/`):

```powershell
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0.0.0"}}}' |
  ..\backend\.venv\Scripts\python.exe -m mcp_server.server
```

A JSON response with `"serverInfo":{"name":"growthloop"}` means the
server starts and speaks the protocol. (Piping closes stdin, so the
server exits right after responding — that is expected.) The pytest
suite also spawns the server and drives all seven tools over stdio:
from `backend/`, `pytest tests/test_mcp_server.py`.

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| Server missing in Claude Desktop | Config JSON syntax error (trailing commas, unescaped `\`), wrong path, or Claude Desktop not fully restarted. Re-check `claude_desktop_config.json`. |
| Tool calls fail with `password authentication failed for user "postgres"` | PostgreSQL credentials mismatch: start it with `docker compose up -d` and check `DATABASE_URL` / `.env` against [docs/DATABASE.md](DATABASE.md). |
| Tool calls fail with `connection refused` / database does not exist | PostgreSQL is not running, or the database name in `DATABASE_URL` is wrong. `docker compose up -d`, then `alembic upgrade head` from `backend/`. |
| Server starts then tools report errors immediately | Migrations not applied: run `alembic upgrade head` from `backend/` with the venv active. |
| `python.exe` path not found | The venv was never created — run the prerequisites above; adjust the path in the Claude config if the repo lives elsewhere. |
| Changes to `mcp_server/` not picked up | If you launch via `growthloop-mcp.exe`, re-run `pip install -e .` after pulling changes; the `python -m mcp_server.server` form always runs the current source. |
| Need server-side diagnostics | The server writes diagnostics to **stderr** only (stdout carries protocol messages). Claude Desktop captures them in `%APPDATA%\Claude\logs\` — look for `mcp*.log` files mentioning `growthloop`. |

Manual run for debugging (it just waits on stdin — that is normal for a
stdio server; Ctrl+C to stop):

```powershell
cd backend
.venv\Scripts\python.exe -m mcp_server.server
```
