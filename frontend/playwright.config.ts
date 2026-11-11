import { defineConfig } from '@playwright/test'

import {
  BACKEND_ORIGIN,
  BACKEND_PORT,
  FRONTEND_ORIGIN,
  FRONTEND_PORT,
  backendDir,
  frontendDir,
  resolveBackendPython,
  resolveE2eDatabaseUrl,
} from './tests/e2e-env'

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  // One worker keeps the shared throwaway database deterministic: every spec
  // resets and seeds it in beforeAll.
  workers: 1,
  fullyParallel: false,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL: FRONTEND_ORIGIN,
    // Stable locale/timezone so date and currency formatting is deterministic.
    locale: 'en-US',
    timezoneId: 'UTC',
  },
  globalSetup: './tests/global-setup.ts',
  webServer: [
    {
      // Real FastAPI backend on a dedicated port, pointed at the throwaway
      // e2e database. The engine connects lazily, so /health answers before
      // the database reset (global setup) has finished if it runs later.
      command: `"${resolveBackendPython()}" -m uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      url: `${BACKEND_ORIGIN}/health`,
      cwd: backendDir,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        DATABASE_URL: resolveE2eDatabaseUrl(),
        CORS_ORIGINS: `${FRONTEND_ORIGIN},http://127.0.0.1:${FRONTEND_PORT}`,
      },
    },
    {
      // Real Vite dev server on a dedicated port; strictPort guarantees the
      // origin matches the backend's CORS_ORIGINS above.
      command: `npm run dev -- --port ${FRONTEND_PORT} --strictPort`,
      url: FRONTEND_ORIGIN,
      cwd: frontendDir,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        VITE_API_BASE_URL: BACKEND_ORIGIN,
      },
    },
  ],
})
