/**
 * Small shared hook for pages that fetch data: loading/error/ready state
 * plus a retry function. `deps` controls when the loader re-runs (like an
 * effect dependency list; values must be JSON-serializable); `reload`
 * re-runs it on demand. The loading state is derived from the current
 * request key, so the hook never sets state synchronously inside effects.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { toApiError } from './api'

export type AsyncData<T> =
  | { status: 'loading'; data: null; message: null; reload: () => void }
  | { status: 'error'; data: null; message: string; reload: () => void }
  | { status: 'ready'; data: T; message: null; reload: () => void }

type Result<T> =
  | { key: string; status: 'ready'; data: T }
  | { key: string; status: 'error'; message: string }

export function useAsyncData<T>(
  loader: () => Promise<T>,
  deps: readonly unknown[],
): AsyncData<T> {
  const [nonce, setNonce] = useState(0)
  const [result, setResult] = useState<Result<T> | null>(null)
  const key = `${JSON.stringify(deps)}:${nonce}`
  const loaderRef = useRef(loader)
  useEffect(() => {
    loaderRef.current = loader
  })

  useEffect(() => {
    let alive = true
    loaderRef.current().then(
      (data) => {
        if (alive) setResult({ key, status: 'ready', data })
      },
      (error: unknown) => {
        if (alive) setResult({ key, status: 'error', message: toApiError(error).message })
      },
    )
    return () => {
      alive = false
    }
  }, [key])

  const reload = useCallback(() => setNonce((previous) => previous + 1), [])

  if (result && result.key === key) {
    return result.status === 'error'
      ? { status: 'error', data: null, message: result.message, reload }
      : { status: 'ready', data: result.data, message: null, reload }
  }
  return { status: 'loading', data: null, message: null, reload }
}
