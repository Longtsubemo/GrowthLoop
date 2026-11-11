/**
 * Drive the real GrowthLoop MCP server from Playwright.
 *
 * Playwright runs in Node and cannot import the Python MCP SDK, so each call
 * shells out to `backend/scripts/mcp_call.py`, which speaks MCP over stdio to
 * `python -m mcp_server.server`. The database URL is the same throwaway
 * `growthloop_e2e` database used by the Playwright backend.
 */

import { spawnSync } from 'node:child_process'

import { backendDir, resolveBackendPython, resolveE2eDatabaseUrl } from './e2e-env'

export function runMcp(
  tool: string,
  args: Record<string, unknown>,
): Record<string, unknown> {
  const result = spawnSync(
    resolveBackendPython(),
    ['scripts/mcp_call.py', tool, JSON.stringify(args)],
    {
      cwd: backendDir,
      env: { ...process.env, DATABASE_URL: resolveE2eDatabaseUrl() },
      encoding: 'utf8',
      timeout: 30_000,
    },
  )

  if (result.error) throw result.error
  if (result.status !== 0) {
    throw new Error(
      `MCP tool ${tool} failed (${result.status}): ${result.stderr || result.stdout}`,
    )
  }

  const output = result.stdout.trim()
  if (!output) throw new Error(`MCP tool ${tool} returned no output`)
  return JSON.parse(output) as Record<string, unknown>
}
