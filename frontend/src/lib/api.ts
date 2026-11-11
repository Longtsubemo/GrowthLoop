import axios from 'axios'

// Base URL comes from VITE_API_BASE_URL (see .env.example at the repo root).
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  withCredentials: true,
})

export interface OwnerSession {
  authenticated: boolean
  csrf_token: string | null
}

// This token exists only in application memory and is refreshed from the
// HttpOnly session endpoint after each page load.
let csrfToken: string | null = null

api.interceptors.request.use((config) => {
  const method = (config.method ?? 'get').toLowerCase()
  if (csrfToken && !['get', 'head', 'options'].includes(method)) {
    config.headers.set('X-CSRF-Token', csrfToken)
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (
      axios.isAxiosError(error) &&
      error.response?.status === 401 &&
      !String(error.config?.url ?? '').startsWith('/api/v1/auth/') &&
      typeof window !== 'undefined'
    ) {
      window.dispatchEvent(new Event('growthloop:auth-expired'))
    }
    return Promise.reject(error)
  },
)

export async function getOwnerSession(): Promise<OwnerSession> {
  const response = await api.get<OwnerSession>('/api/v1/auth/session')
  csrfToken = response.data.authenticated ? response.data.csrf_token : null
  return response.data
}

export async function loginOwner(password: string): Promise<OwnerSession> {
  const response = await api.post<OwnerSession>('/api/v1/auth/login', { password })
  csrfToken = response.data.csrf_token
  return response.data
}

export async function logoutOwner(): Promise<void> {
  await api.post('/api/v1/auth/logout')
  csrfToken = null
}

/** Experiment lifecycle states, mirroring the backend ExperimentStatus enum. */
export const EXPERIMENT_STATUSES = [
  'draft',
  'planned',
  'running',
  'completed',
  'paused',
  'cancelled',
] as const

export type ExperimentStatus = (typeof EXPERIMENT_STATUSES)[number]

/**
 * An experiment as returned by the API. Field names and types mirror the
 * backend ExperimentResponse schema (backend/app/schemas/experiment.py).
 * budget_amount is a decimal string like "15000.50" — it is kept as a
 * string everywhere to preserve precision.
 */
export interface Experiment {
  id: string
  title: string
  hypothesis: string
  target_audience: string
  channel: string
  budget_amount: string | null
  currency_code: string
  status: ExperimentStatus
  execution_steps: string[]
  success_metric: string
  actual_result: string | null
  created_at: string
  updated_at: string
}

/** One page of experiments plus pagination metadata (GET /experiments). */
export interface ExperimentListResponse {
  items: Experiment[]
  total: number
  limit: number
  offset: number
}

/**
 * Payload the dashboard form submits for create and update. The backend
 * remains the source of truth for validation; this shape matches its
 * ExperimentCreate/ExperimentUpdate schemas. Every field is sent as a
 * trimmed string (or null for the optional ones) so decimal precision
 * survives the round trip.
 */
export interface ExperimentSubmitPayload {
  title: string
  hypothesis: string
  target_audience: string
  channel: string
  budget_amount: string | null
  currency_code: string
  execution_steps: string[]
  success_metric: string
  actual_result: string | null
}

/** The PATCH endpoint also accepts partial payloads. */
export type ExperimentUpdatePayload = Partial<ExperimentSubmitPayload>

export async function listExperiments(
  params: { status?: ExperimentStatus; limit?: number; offset?: number } = {},
): Promise<ExperimentListResponse> {
  const response = await api.get<ExperimentListResponse>('/api/v1/experiments', {
    params,
  })
  return response.data
}

export async function getExperiment(id: string): Promise<Experiment> {
  const response = await api.get<Experiment>(`/api/v1/experiments/${id}`)
  return response.data
}

export async function createExperiment(
  payload: ExperimentSubmitPayload,
): Promise<Experiment> {
  const response = await api.post<Experiment>('/api/v1/experiments', payload)
  return response.data
}

export async function updateExperiment(
  id: string,
  payload: ExperimentUpdatePayload,
): Promise<Experiment> {
  const response = await api.patch<Experiment>(`/api/v1/experiments/${id}`, payload)
  return response.data
}

export async function updateExperimentStatus(
  id: string,
  status: ExperimentStatus,
): Promise<Experiment> {
  const response = await api.patch<Experiment>(`/api/v1/experiments/${id}/status`, {
    status,
  })
  return response.data
}

export async function recordExperimentResult(
  id: string,
  actualResult: string,
): Promise<Experiment> {
  const response = await api.patch<Experiment>(
    `/api/v1/experiments/${id}/result`,
    { actual_result: actualResult },
  )
  return response.data
}

export async function deleteExperiment(id: string): Promise<void> {
  await api.delete(`/api/v1/experiments/${id}`)
}

export interface ApiErrorInfo {
  /** User-facing summary of what went wrong. */
  message: string
  /** FastAPI 422 details keyed by form field name, when available. */
  fieldErrors: Record<string, string>
}

/**
 * Translate an error thrown by the API functions into something the UI can
 * show: a readable message plus per-field validation errors when the
 * backend rejected specific fields. Never exposes stack traces.
 */
export function toApiError(error: unknown): ApiErrorInfo {
  if (axios.isAxiosError(error)) {
    const detail = (
      error.response?.data as { detail?: unknown } | undefined
    )?.detail

    if (Array.isArray(detail)) {
      const fieldErrors: Record<string, string> = {}
      for (const item of detail) {
        if (
          typeof item === 'object' &&
          item !== null &&
          'loc' in item &&
          'msg' in item &&
          Array.isArray(item.loc)
        ) {
          const [scope, field] = item.loc
          if (scope === 'body' && typeof field === 'string') {
            fieldErrors[field] = String(item.msg)
          }
        }
      }
      if (Object.keys(fieldErrors).length > 0) {
        return {
          message: 'The server rejected some fields. Please fix them and try again.',
          fieldErrors,
        }
      }
      return { message: 'The submitted data is invalid.', fieldErrors: {} }
    }

    if (typeof detail === 'string' && detail) {
      return { message: detail, fieldErrors: {} }
    }

    if (!error.response) {
      return {
        message: 'Could not reach the GrowthLoop server. Is the backend running?',
        fieldErrors: {},
      }
    }
  }
  return { message: 'Something went wrong. Please try again.', fieldErrors: {} }
}
