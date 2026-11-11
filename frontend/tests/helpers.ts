/**
 * Node-side API helpers for seeding and verifying e2e state.
 *
 * These use plain `fetch` against the real backend (src/lib/api.ts cannot be
 * imported in Node because it reads `import.meta.env`, which only exists in
 * the browser bundle). Types mirror the backend schemas.
 */

import { BACKEND_ORIGIN } from './e2e-env'

export type ExperimentStatusValue =
  | 'draft'
  | 'planned'
  | 'running'
  | 'completed'
  | 'paused'
  | 'cancelled'

export interface ExperimentRecord {
  id: string
  title: string
  hypothesis: string
  target_audience: string
  channel: string
  budget_amount: string | null
  currency_code: string
  status: ExperimentStatusValue
  execution_steps: string[]
  success_metric: string
  actual_result: string | null
  created_at: string
  updated_at: string
}

export interface ExperimentInput {
  title: string
  hypothesis: string
  target_audience: string
  channel: string
  success_metric: string
  status?: ExperimentStatusValue
  budget_amount?: string | null
  currency_code?: string
  execution_steps?: string[]
  actual_result?: string | null
}

const API_URL = `${BACKEND_ORIGIN}/api/v1/experiments`

async function request(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { 'content-type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    const body = await response.text()
    throw new Error(`API request failed (${response.status}): ${body}`)
  }
  return response
}

/** Fetch every experiment (following pagination), optionally filtered by status. */
export async function listAll(status?: ExperimentStatusValue): Promise<ExperimentRecord[]> {
  const records: ExperimentRecord[] = []
  let offset = 0
  for (let guard = 0; guard < 100; guard += 1) {
    const query = new URLSearchParams({ limit: '100', offset: String(offset) })
    if (status) query.set('status', status)
    const response = await request(`?${query.toString()}`)
    const page = (await response.json()) as { items: ExperimentRecord[]; total: number }
    records.push(...page.items)
    if (page.items.length === 0 || records.length >= page.total) break
    offset += page.items.length
  }
  return records
}

export async function createExperiment(input: ExperimentInput): Promise<ExperimentRecord> {
  const response = await request('', {
    method: 'POST',
    body: JSON.stringify({
      title: input.title,
      hypothesis: input.hypothesis,
      target_audience: input.target_audience,
      channel: input.channel,
      success_metric: input.success_metric,
      status: input.status ?? 'draft',
      budget_amount: input.budget_amount ?? null,
      currency_code: input.currency_code ?? 'INR',
      execution_steps: input.execution_steps ?? [],
      actual_result: input.actual_result ?? null,
    }),
  })
  return (await response.json()) as ExperimentRecord
}

/** Remove every experiment so a spec can seed a known state. */
export async function deleteAllExperiments(): Promise<void> {
  for (const record of await listAll()) {
    await request(`/${record.id}`, { method: 'DELETE' })
  }
}

export interface SeedSpec {
  title: string
  status?: ExperimentStatusValue
  channel?: string
  budgetAmount?: string | null
  currencyCode?: string
  steps?: string[]
}

/** Create a set of experiments in order (the API lists them newest first). */
export async function seedExperiments(seeds: SeedSpec[]): Promise<ExperimentRecord[]> {
  const records: ExperimentRecord[] = []
  for (const seed of seeds) {
    records.push(
      await createExperiment({
        title: seed.title,
        hypothesis: `Hypothesis for ${seed.title}`,
        target_audience: 'Startup founders evaluating GrowthLoop',
        channel: seed.channel ?? 'landing_page',
        success_metric: 'Signups per week',
        status: seed.status,
        budget_amount: seed.budgetAmount ?? null,
        currency_code: seed.currencyCode ?? 'INR',
        execution_steps: seed.steps ?? [`Run ${seed.title}`],
        actual_result: null,
      }),
    )
  }
  return records
}
