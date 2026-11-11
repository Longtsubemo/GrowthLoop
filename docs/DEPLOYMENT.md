# Free-tier deployment preparation

This guide prepares a manual deployment to Render using the existing Neon
project described below. No Render service is created by this repository. The
documented free plans are suitable for a demo or hobby deployment, not
production-grade uptime or backup guarantees. Provider quotas change; this
guide was checked on 2026-11-12.

The repository's [`render.yaml`](../render.yaml) describes a Render Free Web
Service and a Render Static Site on the existing `dev` branch. `autoDeployTrigger`
is off. Applying the Blueprint still creates and initially deploys services;
wait for explicit approval before doing that. The API and OAuth state remain
in process memory, so the backend is configured with exactly one Uvicorn
worker.

## 1. Use the existing Neon database

GrowthLoop is already connected to the existing Neon project
`my-first-project`, on its `production` branch and `neondb` database. The
GrowthLoop migration has been applied, and the dedicated `growthloop_app`
runtime role has been created and verified. Do not create another project,
branch, or database as part of this deployment.

The local, gitignored `backend/.env` keeps two separate values:

- `DATABASE_URL` is the existing `neondb_owner` connection retained for
  local administration and migrations. Do not use this owner connection as
  the deployed application's database credential.
- `GROWTHLOOP_APP_DATABASE_URL` is the verified pooled connection for
  `growthloop_app`. It is a local handoff value; application settings do not
  read this name, and Render cannot read a developer's local `.env` file.

The runtime role can connect to `neondb`, use the `public` schema, and perform
CRUD on `public.experiments`. It does not own the database or application
objects and has no schema creation or Alembic migration-table privileges.
Keep the `neondb_owner` connection separate and use a **direct** (pooling
disabled) owner URI for any reviewed migration.

In the Neon **Connect** dialog, select the existing `production` branch,
`neondb`, and `growthloop_app`, then enable connection pooling. The pooled
hostname uses Neon's `-pooler` endpoint and the URI must retain TLS settings
such as `sslmode=require` and any provider-supplied `channel_binding`
parameter. The application accepts Neon's `postgresql://` format and
normalizes it to SQLAlchemy's `postgresql+psycopg://` driver while preserving
the query parameters. Production startup rejects URLs without exactly one
`sslmode` of `require`, `verify-ca`, or `verify-full`.

Render does not support Blueprint interpolation from a local `.env` value.
The Blueprint therefore declares `DATABASE_URL` with `sync: false`; enter the
value of `GROWTHLOOP_APP_DATABASE_URL` manually in the Render Dashboard as the
backend service's `DATABASE_URL`. Never enter the owner URL there. Do not put
either URL in this repository, documentation, or frontend configuration.
Neon's [connection guide](https://neon.com/docs/connect/connect-from-any-app)
covers pooled and direct connection strings.

Neon currently documents a Free allowance of 100 CU-hours per project each
month, up to 2 CU autoscaling, 1 GB of Postgres storage per project (20 GB per
account), and 5 GB of monthly public network transfer per project. Free
compute scales to zero after 5 minutes idle. Free instant restore covers at
most 6 hours or 1 GB of change history; scheduled backup snapshots are not
included, only one manual snapshot is allowed, and there is no uptime SLA.
The allowance is shared with other usage in the project, so monitor Neon
usage. Maintain and periodically verify your own `pg_dump` backups outside the
Render filesystem; that filesystem is ephemeral. See [Neon plan limits](https://neon.com/docs/introduction/plans)
and [scale to zero](https://neon.com/docs/introduction/scale-to-zero).

## 2. Create the Render services from the Blueprint

Manual Render Dashboard actions:

1. Connect the GrowthLoop Git repository to Render and choose the existing
   `dev` branch. Open **New → Blueprint**, select the repository's root
   `render.yaml`, and review the two services before applying it.
2. For the backend's `DATABASE_URL` prompt, manually copy the value of local
   `GROWTHLOOP_APP_DATABASE_URL` into Render. It must be the pooled
   `growthloop_app` URI; do not use local `DATABASE_URL`, which is retained
   for owner administration. For `OWNER_PASSWORD`, enter a unique 16–1024
   character secret. For `CORS_ORIGINS`, enter the exact HTTPS origin of the
   planned Render static site, such as
   `https://growthloop-dashboard.onrender.com`. Confirm the generated URLs
   after creation; if Render assigned a different hostname, update
   `CORS_ORIGINS` in the backend service environment.
3. The Blueprint derives `MCP_ISSUER_URL` and `MCP_ALLOWED_HOSTS` from the
   backend's Render external URL and hostname. `MCP_ALLOWED_ORIGINS` is
   deliberately empty by default: requests without an Origin are accepted,
   while any supplied Origin is rejected. The SDK validates Host and Origin
   for `/mcp`; FastAPI's trusted-host middleware checks Host for all routes.
   OAuth endpoint CORS is also restricted by the exact `MCP_ALLOWED_ORIGINS`
   list; the SDK's internal wildcard CORS response is removed before FastAPI
   applies the allowlist. `CORS_ORIGINS` is the dashboard's exact HTTPS origin
   and is configured separately.
4. Do not guess a Claude connector Origin. This repository has not verified
   whether Claude sends an Origin header on remote MCP or OAuth requests. If a
   client sends one, inspect that actual request or use authoritative client
   documentation, then add only its exact HTTPS origin to
   `MCP_ALLOWED_ORIGINS` in the backend service environment. Until verified,
   an Origin-bearing request is intentionally rejected.
5. The frontend's build-time `VITE_API_BASE_URL` references the backend's
   Render external URL. It contains no credential. The static site builds
   from `frontend` with `npm ci && npm run build` and publishes `dist`. The
   repository pins Node.js through `frontend/.node-version`.
6. Review the backend environment. The names configured by the Blueprint are
   `APP_ENV`, `DEBUG`, `DATABASE_URL`, `OWNER_PASSWORD`,
   `OWNER_SESSION_TTL_SECONDS`, `MCP_ISSUER_URL`, `MCP_ALLOWED_HOSTS`,
   `MCP_ALLOWED_ORIGINS`, `CORS_ORIGINS`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
   `DB_POOL_TIMEOUT_SECONDS`, `DB_POOL_RECYCLE_SECONDS`, and
   `DB_CONNECT_TIMEOUT_SECONDS`. The frontend build variable is
   `VITE_API_BASE_URL` and `NODE_VERSION`. Render supplies `PORT`; the start
   command binds to `0.0.0.0:$PORT` and starts exactly one Uvicorn worker.
7. If you later add custom domains, update `MCP_ISSUER_URL`,
   `MCP_ALLOWED_HOSTS`, `CORS_ORIGINS`, and `VITE_API_BASE_URL` to match the
   actual public URLs. Keep each value exact and use HTTPS.

Render prompts for `sync: false` values during initial Blueprint creation.
Render does not interpolate one environment variable into another, and a
Blueprint cannot read `GROWTHLOOP_APP_DATABASE_URL` from the local machine.
When configuring an existing Render service or changing a `sync: false`
value, enter `DATABASE_URL`, `OWNER_PASSWORD`, and `CORS_ORIGINS` manually in
that service's Environment page, then redeploy. Never commit those values.
`MCP_ALLOWED_ORIGINS` is intentionally empty until the actual MCP client's
Origin behavior is known; if a client sends an Origin, add only its exact
verified HTTPS origin in the service environment.

## 3. Apply migrations manually

The Render Web Service does not run migrations during application startup.
Run Alembic from a trusted local checkout using the Neon **direct** owner URI
only when a reviewed migration is pending. Confirm the database, role, and
branch before proceeding. The current Alembic configuration reads
`DATABASE_URL`; it does not support `MIGRATION_DATABASE_URL`. For a one-off
migration, set `DATABASE_URL` in that command's process to the direct owner
URI, then remove the process override. The deployed service's `DATABASE_URL`
must remain the pooled `growthloop_app` URI.

From `backend/` in PowerShell, with the project's Python 3.12 virtual
environment installed:

```powershell
$previousDatabaseUrl = $env:DATABASE_URL
$previousAppEnv = $env:APP_ENV
$secureDatabaseUrl = Read-Host 'Paste the Neon direct owner connection URI' -AsSecureString
$databaseUrlPointer = [IntPtr]::Zero
try {
    $databaseUrlPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureDatabaseUrl)
    $env:DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($databaseUrlPointer)
    $env:APP_ENV = 'development'
    .venv\Scripts\python.exe -m alembic current
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the current migration revision.' }
    .venv\Scripts\python.exe -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Migration failed; stop and inspect the Alembic output.' }
    .venv\Scripts\python.exe -m alembic current
    if ($LASTEXITCODE -ne 0) { throw 'Could not verify the resulting migration revision.' }
}
finally {
    if ($databaseUrlPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($databaseUrlPointer)
    }
    $secureDatabaseUrl.Dispose()
    if ($null -eq $previousDatabaseUrl) {
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    } else {
        $env:DATABASE_URL = $previousDatabaseUrl
    }
    if ($null -eq $previousAppEnv) {
        Remove-Item Env:APP_ENV -ErrorAction SilentlyContinue
    } else {
        $env:APP_ENV = $previousAppEnv
    }
    Remove-Variable previousDatabaseUrl, previousAppEnv, secureDatabaseUrl, databaseUrlPointer -ErrorAction SilentlyContinue
}
```

The migration command uses the direct owner connection only for the schema
change. The deployed application continues to use the pooled,
least-privilege `growthloop_app` URI. Re-run this migration procedure only
when a reviewed change adds a migration; it is not part of the Render start
command.

## 4. Deploy and configure the dashboard

After the Blueprint configuration is reviewed and deployment is approved,
manually apply the Blueprint in Render. Check both deploy logs and service
URLs. Confirm the backend's `MCP_ISSUER_URL` matches its external HTTPS URL,
the `MCP_ALLOWED_HOSTS` value is the matching hostname, and `CORS_ORIGINS`
matches the static site's exact origin. Confirm `VITE_API_BASE_URL` is the
backend URL, not localhost, then trigger a frontend rebuild if its value
changed.

The dashboard uses hash-based routes (`/#/...`), so a page reload requests
the static site's root document; no server-side SPA rewrite is required.
Sign in with `OWNER_PASSWORD`. Browser REST calls use the HttpOnly owner
session cookie and CSRF token; neither is included in the frontend build.

## 5. Smoke checks

Replace the host placeholders with the URLs shown in Render. The first
backend request after idle can take about a minute while Render starts the
free instance.

```powershell
$api = 'https://<backend-host>.onrender.com'
Invoke-RestMethod "$api/health"                 # { status: "ok" }
Invoke-RestMethod "$api/health/ready"           # { status: "ready" }
Invoke-WebRequest "$api/api/v1/experiments"     # 401 without owner session
Invoke-WebRequest "$api/.well-known/oauth-protected-resource/mcp"
Invoke-WebRequest "$api/mcp" -Method Post       # 401 without OAuth bearer token
```

Then open the static-site URL, sign in, and confirm the dashboard loads
experiments. For remote MCP, configure a compatible OAuth MCP client with
`https://<backend-host>.onrender.com/mcp` and complete the owner consent flow.
Verify create/read/update/delete through both MCP and the dashboard before
sharing the endpoint. Local Claude Desktop stdio configuration remains as
described in [MCP.md](MCP.md).

## Free-tier operations and limitations

- **Render Free Web Service:** sleeps after 15 minutes without inbound
  traffic and can take about a minute to wake. Render may restart it at any
  time, its filesystem is ephemeral, and it has no always-on guarantee. Free
  web services share a 750 instance-hour monthly allowance per workspace;
  bandwidth and build-pipeline quotas also apply. Render itself advises
  against using free instances for production applications. [Render free
  limits](https://render.com/docs/free).
- **Render Static Site:** free hosting is served through Render's CDN and
  does not need an application process, but it still counts against monthly
  bandwidth and build-pipeline allowances. [Static site Blueprint fields](https://render.com/docs/blueprint-spec).
- **Neon Free:** database compute sleeps after five idle minutes, then wakes
  on demand; Free has finite compute, storage, and transfer limits, short
  restore history, no scheduled backups, and no uptime SLA. The plan currently
  permits a manual snapshot, but snapshot storage may incur a separate charge;
  omit it if maintaining a strict zero-cost setup. Verify current quotas and
  pricing before use. [Neon plans](https://neon.com/docs/introduction/plans),
  [scale to zero](https://neon.com/docs/introduction/scale-to-zero).
- **App authentication state:** owner sessions, OAuth registrations, pending
  consent requests, and tokens live in one backend process. Render sleep,
  restart, or deploy clears them, so an owner may need to sign in or authorize
  again. Keep the one-worker configuration. Do not horizontally scale this
  application without a shared persistent state store.
- **Abuse limits:** OAuth registration is limited to ten requests per
  server-observed client address per hour; login failures are limited to five
  per address per 15 minutes. Both limiters have bounded in-process state and
  reset on restart. Confirm how the hosting proxy reports client addresses
  before relying on per-address throttling; the app does not trust arbitrary
  forwarding headers.
- **Backups:** Render's filesystem is not a backup destination. Neon Free's
  restore window is limited and scheduled backups are not included. Keep
  independent `pg_dump` exports outside Neon and verify that they can be
  restored. Render Free may suspend services after included monthly allowances
  are exhausted when there is no billing method; check the current limits and
  usage regularly. [Render free limits](https://render.com/docs/free).

This setup is cost-constrained and intentionally has no production uptime,
availability, or durable-backup guarantee. It creates no Render Postgres,
Redis, paid service, or external authentication dependency.
