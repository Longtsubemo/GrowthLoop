# GrowthLoop frontend

React + Vite + TypeScript + Tailwind CSS dashboard for GrowthLoop. Humans
review and edit every experiment here; Claude reaches the same data through
the MCP server and shared backend services.

## Pages

| Route | Purpose |
| --- | --- |
| `#/` | Overview: total, draft/planned, running, completed, recent six |
| `#/experiments` | List with status filter, pagination, and create action |
| `#/experiments/new` | Create form |
| `#/experiments/:id` | Detail: status change, result recording, confirmed delete |
| `#/experiments/:id/edit` | Edit form |

The form uses client-side validation for usability only; the backend
remains the source of truth and its field errors are shown inline. Budgets
are kept as decimal strings so precision survives the round trip.

## Commands (run from this directory)

```powershell
npm install       # install dependencies
npm run dev       # dev server at http://localhost:5173
npm run build     # type-check and build for production
npm run preview   # preview the production build
npm run lint      # oxlint
```

Set `VITE_API_BASE_URL` to point at a non-default backend (the default is
`http://localhost:8000`).

## Browser tests (Playwright)

```powershell
npx playwright install chromium   # one-time browser download
npm run test:e2e                  # real API + throwaway database
```

The suite starts the real FastAPI backend (port 8377, from
`backend/.venv`) and Vite (port 5174), and resets the dedicated
`growthloop_e2e` PostgreSQL database via
`backend/scripts/reset_e2e_database.py` before running. PostgreSQL must be
up (`docker compose up -d` from the repository root). Development data is
never touched.

See the root README and `docs/DEVELOPMENT.md` for the full project setup.
