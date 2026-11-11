/**
 * Shared constants and path/URL resolution for the Playwright e2e suite.
 *
 * The suite runs the real FastAPI backend and the real Vite dev server on
 * dedicated ports, against a throwaway PostgreSQL database (`growthloop_e2e`)
 * on the same server as `DATABASE_URL` — the same isolation strategy as the
 * backend's pytest conftest. Development data is never touched.
 */

import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const testsDir = dirname(fileURLToPath(import.meta.url))
/** Absolute path of `frontend/`. */
export const frontendDir = resolve(testsDir, '..')
/** Absolute path of the repository root. */
export const repoRoot = resolve(frontendDir, '..')
/** Absolute path of `backend/`. */
export const backendDir = join(repoRoot, 'backend')

/** Ports chosen so the suite never collides with the everyday dev servers (5173 / 8000). */
export const FRONTEND_PORT = 5174
export const BACKEND_PORT = 8377
export const FRONTEND_ORIGIN = `http://localhost:${FRONTEND_PORT}`
export const BACKEND_ORIGIN = `http://localhost:${BACKEND_PORT}`

/** Throwaway database used by the e2e suite (never the development database). */
export const E2E_DATABASE_NAME = 'growthloop_e2e'

/** The backend virtual environment's Python interpreter (the project pins 3.12). */
export function resolveBackendPython(): string {
  const candidates = [
    join(backendDir, '.venv', 'Scripts', 'python.exe'), // Windows
    join(backendDir, '.venv', 'bin', 'python'), // Linux / macOS
  ]
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate
  }
  throw new Error(
    'backend/.venv was not found. Create it first (from backend/): ' +
      'py -3.12 -m venv .venv; pip install -e ".[dev]"',
  )
}

function readEnvFile(path: string): Record<string, string> {
  if (!existsSync(path)) return {}
  const values: Record<string, string> = {}
  for (const line of readFileSync(path, 'utf8').split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const separator = trimmed.indexOf('=')
    if (separator === -1) continue
    values[trimmed.slice(0, separator).trim()] = trimmed
      .slice(separator + 1)
      .trim()
  }
  return values
}

/**
 * Database URL for the e2e run: the same PostgreSQL server as
 * `DATABASE_URL` (process environment, then the repo `backend/.env`, then
 * the root `.env`, then the docker-compose default), but pointing at the
 * throwaway `growthloop_e2e` database.
 */
export function resolveE2eDatabaseUrl(): string {
  let url = process.env.DATABASE_URL
  if (!url) {
    const fileEnv = {
      ...readEnvFile(join(repoRoot, '.env')),
      ...readEnvFile(join(backendDir, '.env')),
    }
    url = fileEnv.DATABASE_URL
  }
  if (!url) {
    url = 'postgresql+psycopg://postgres:postgres@localhost:5432/growthloop'
  }
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    throw new Error('Could not derive the isolated e2e database URL from DATABASE_URL.')
  }
  const hostname = parsed.hostname.toLowerCase()
  const isLoopback =
    hostname === 'localhost' ||
    hostname === '[::1]' ||
    /^127\.(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)){2}$/.test(
      hostname,
    )
  if (!isLoopback) {
    throw new Error('The e2e suite only permits a local PostgreSQL database.')
  }
  const replaced = url.replace(/^(.*\/\/.*\/)[^/?]+(\?.*)?$/, `$1${E2E_DATABASE_NAME}$2`)
  if (!replaced.includes(`/${E2E_DATABASE_NAME}`)) {
    throw new Error('Could not derive the isolated e2e database URL from DATABASE_URL.')
  }
  return replaced
}
