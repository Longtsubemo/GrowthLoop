/**
 * Playwright global setup: recreate the throwaway e2e database and apply all
 * Alembic migrations to it, so the suite always starts from a clean, fully
 * migrated schema. Fails fast with a hint when PostgreSQL is not running.
 */

import { spawnSync } from 'node:child_process'

import { backendDir, resolveBackendPython, resolveE2eDatabaseUrl } from './e2e-env'

export default async function globalSetup(): Promise<void> {
  const python = resolveBackendPython()
  const databaseUrl = resolveE2eDatabaseUrl()
  const result = spawnSync(python, ['scripts/reset_e2e_database.py'], {
    cwd: backendDir,
    stdio: ['pipe', 'inherit', 'inherit'],
    input: databaseUrl,
  })
  if (result.error) {
    throw result.error
  }
  if (result.status !== 0) {
    throw new Error(
      'Could not reset the e2e database. PostgreSQL must be running for the e2e ' +
        'suite — start it with `docker compose up -d` from the repository root.',
    )
  }
}
