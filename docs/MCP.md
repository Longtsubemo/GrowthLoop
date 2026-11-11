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

## Streamable HTTP endpoint

Render and Neon production preparation, including exact hostname/origin
configuration and the current one-worker/free-tier limitations, is in
[DEPLOYMENT.md](DEPLOYMENT.md).

The same FastAPI process also serves the seven tools over MCP Streamable
HTTP at `/mcp`. It uses the MCP SDK 2.3 stateless HTTP transport because the
experiment tools do not keep per-client protocol state. REST and MCP share
the same seven tool registrations, service layer, and database session
factory. The FastAPI lifespan starts and stops the SDK session manager.

The HTTP resource requires OAuth access tokens, uses authorization code with
PKCE and dynamic client registration, and presents an owner approval page.
The owner signs in with `OWNER_PASSWORD`; access tokens are short lived and
refresh tokens rotate. Dashboard REST requests instead use an HttpOnly owner
session cookie and synchronizer CSRF token. Local stdio is unchanged and is
intended for trusted local MCP clients.

OAuth requires the canonical MCP resource URL in authorization and token
requests. The server rejects missing or mismatched token-request resources,
issues access and refresh tokens only for `/mcp`, and the SDK rejects tokens
whose resource does not match that endpoint. Authorization responses include
`iss`; OAuth metadata advertises that parameter. The installed MCP SDK client
validates a present `iss` against the discovered issuer and rejects a missing
value when the server advertises support.

Dynamic registration accepts HTTPS callbacks and HTTP callbacks only for
`localhost` or an IP loopback address. It rejects fragments, user information,
missing hosts, other schemes, and any registration containing an invalid
callback. Registration is limited to ten requests per observed client address
per hour, the process retains at most 512 clients, and inactive registrations
expire after 30 days. Pending authorizations, codes, and token pairs also have
fixed process-local capacity limits. These are single-process abuse controls;
they do not provide a distributed rate limit.

Authentication is implemented locally, but **remote MCP has not been
deployed or verified against a live public Claude connector**. Do not treat
this repository as a publicly hosted service. Remote use requires HTTPS and
the exact host and origin configuration below. Authentication protects the
HTTP resource; Host and Origin allowlists are additional transport checks.

### Local HTTP testing

From `backend/`, start the hosted app after PostgreSQL is running and the
schema is current:

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Before starting the app, configure `OWNER_PASSWORD` in the root `.env` to a
unique value of at least 16 characters. No default password is provided.
The local endpoint is `http://localhost:8000/mcp`; the OAuth issuer is
`http://localhost:8000`. Development defaults allow local API hostnames and
the dashboard origins on port 5173. The dashboard login is at
`http://localhost:5173`.
For automated protocol, tool, shared-record, error, and security checks,
run from `backend/`:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_mcp_http.py
```

The HTTP tests use an isolated test database managed by the backend test
fixtures; they do not use the development database for destructive checks.

### Connecting a remote MCP client

Configure the client with the public MCP resource URL, for example
`https://api.example.com/mcp`. A compatible OAuth client discovers the
authorization server metadata, registers with the OAuth server when needed,
and redirects the owner through GrowthLoop's sign-in and consent screen.
The OAuth issuer URL is the API base URL, such as
`https://api.example.com`; do not include `/mcp` in `MCP_ISSUER_URL`.

Claude's [remote connector guide](https://support.anthropic.com/en/articles/11503834-building-custom-connectors-via-remote-mcp)
describes OAuth for servers that require authentication, including dynamic
client registration. This implementation follows that flow; it does not
require a fixed custom bearer header in connector settings. Availability of
custom connectors depends on the Claude plan and account. See also Anthropic's
[connector setup guide](https://support.anthropic.com/en/articles/11175166-about-custom-integrations-using-remote-mcp).

### Remote host configuration expectations

The host must run the FastAPI application and provide a hosted PostgreSQL
`DATABASE_URL`. Configure `APP_ENV=production`, `DEBUG=false`, a strong unique
`OWNER_PASSWORD`, `MCP_ISSUER_URL` as the exact public API base URL, the
dashboard's exact HTTPS `CORS_ORIGINS`, and `MCP_ALLOWED_HOSTS` with the exact
public API hostname (for example, `api.example.com`, without a wildcard).
Set `MCP_ALLOWED_ORIGINS` to exact HTTPS origins only if the MCP client sends
an `Origin` header; an explicitly empty value rejects all supplied origins
while allowing clients that omit the header. Those exact origins are also
included in the app's CORS policy for browser-based clients. The host must
provide HTTPS.

Owner sessions, OAuth client registrations, authorization requests, and
tokens are currently held in process memory. An API restart invalidates them;
run one application worker only. Multi-worker or horizontally scaled hosting
needs a shared persistent session/token store. No such host configuration or
public deployment is included in this phase.

The exact Host and Origin allowlists help block arbitrary Host headers and
DNS-rebinding-style browser requests. They do not authenticate a user; OAuth
authorization is handled separately. Keep the local stdio process restricted
to trusted MCP clients.

The MCP SDK validates the request Host and, when present, Origin on the
Streamable HTTP transport using `MCP_ALLOWED_HOSTS` and
`MCP_ALLOWED_ORIGINS`. FastAPI's `TrustedHostMiddleware` independently checks
Host on all API routes. Browser CORS uses exact origins: `CORS_ORIGINS` is for
the dashboard, and `MCP_ALLOWED_ORIGINS` is for browser-based MCP/OAuth
clients. The SDK 2.3 OAuth helpers emit wildcard CORS headers internally;
the hosted app removes those headers and lets FastAPI add CORS headers only
for configured origins. No wildcard is enabled by the application.

After Render assigns the dashboard hostname, set `CORS_ORIGINS` to that
exact HTTPS origin. Keep `MCP_ALLOWED_ORIGINS` empty unless the intended MCP
client sends an Origin header. Claude's remote connector Origin behavior has
not been verified against a live connection, so do not guess or preconfigure
an origin for it. If an Origin header is observed, add only that exact HTTPS
origin in the backend environment and retest. Requests without Origin remain
allowed by the MCP transport; requests with an unlisted Origin are rejected.
