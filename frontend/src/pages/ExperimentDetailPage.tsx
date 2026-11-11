import { useEffect, useState, type ReactNode } from 'react'

import { ConfirmDialog } from '../components/ConfirmDialog'
import { PencilIcon, TrashIcon } from '../components/icons'
import { StatusBadge } from '../components/StatusBadge'
import { ErrorState, Spinner } from '../components/states'
import {
  EXPERIMENT_STATUSES,
  deleteExperiment as deleteExperimentRequest,
  getExperiment,
  recordExperimentResult,
  toApiError,
  updateExperimentStatus,
  type Experiment,
  type ExperimentStatus,
} from '../lib/api'
import { formatBudget, formatDateTime, statusLabel } from '../lib/format'
import { editExperimentPath, experimentsPath, navigate } from '../lib/router'
import { inputClass } from '../lib/ui'

type FetchState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; experiment: Experiment }

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <h2 className="text-sm font-medium text-slate-500">{title}</h2>
      <div className="mt-2">{children}</div>
    </section>
  )
}

export function ExperimentDetailPage({ id }: { id: string }) {
  // Keyed fetch result: the derived `state` below only uses a result whose
  // key matches the current request, so navigating to another experiment or
  // retrying shows the loading state without setting state synchronously
  // inside the effect. Successful mutations replace the stored experiment
  // under the same key, so the page updates without a refetch.
  const [nonce, setNonce] = useState(0)
  const [fetched, setFetched] = useState<{ key: string; state: FetchState } | null>(
    null,
  )
  const [resultDraftOverride, setResultDraftOverride] = useState<string | null>(null)
  const [savingStatus, setSavingStatus] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [savingResult, setSavingResult] = useState(false)
  const [resultError, setResultError] = useState<string | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const key = `${id}:${nonce}`

  useEffect(() => {
    const requestKey = `${id}:${nonce}`
    let alive = true
    getExperiment(id).then(
      (experiment) => {
        if (alive) setFetched({ key: requestKey, state: { status: 'ready', experiment } })
      },
      (error: unknown) => {
        if (alive) {
          setFetched({
            key: requestKey,
            state: { status: 'error', message: toApiError(error).message },
          })
        }
      },
    )
    return () => {
      alive = false
    }
  }, [id, nonce])

  const state: FetchState =
    fetched !== null && fetched.key === key ? fetched.state : { status: 'loading' }

  if (state.status === 'loading') return <Spinner label="Loading experiment…" />
  if (state.status === 'error') {
    return (
      <ErrorState
        title="Couldn't load experiment"
        message={state.message}
        onRetry={() => setNonce((previous) => previous + 1)}
      />
    )
  }

  const experiment = state.experiment
  // null override means "show whatever the API returned"; typing in the
  // textarea stores an override so an in-progress draft survives a status
  // change, and saving resets it to the server's value.
  const resultDraft = resultDraftOverride ?? experiment.actual_result ?? ''

  const handleStatusChange = async (next: ExperimentStatus) => {
    setSavingStatus(true)
    setStatusError(null)
    try {
      const updated = await updateExperimentStatus(experiment.id, next)
      setFetched({ key, state: { status: 'ready', experiment: updated } })
    } catch (error) {
      setStatusError(toApiError(error).message)
    } finally {
      setSavingStatus(false)
    }
  }

  const handleSaveResult = async () => {
    const text = resultDraft.trim()
    if (!text) {
      setResultError('Result cannot be empty.')
      return
    }
    setSavingResult(true)
    setResultError(null)
    try {
      const updated = await recordExperimentResult(experiment.id, text)
      setFetched({ key, state: { status: 'ready', experiment: updated } })
      setResultDraftOverride(null)
    } catch (error) {
      setResultError(toApiError(error).message)
    } finally {
      setSavingResult(false)
    }
  }

  const handleDelete = async () => {
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteExperimentRequest(experiment.id)
      navigate(experimentsPath)
    } catch (error) {
      setDeleting(false)
      setDeleteError(toApiError(error).message)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <nav aria-label="Breadcrumb">
        <ol className="flex items-center gap-1.5 text-sm">
          <li>
            <a href="#/experiments" className="text-slate-500 hover:text-indigo-600">
              Experiments
            </a>
          </li>
          <li aria-hidden="true" className="text-slate-400">
            /
          </li>
          <li className="max-w-60 truncate font-medium text-slate-900" aria-current="page">
            {experiment.title}
          </li>
        </ol>
      </nav>

      <div className="rounded-lg border border-slate-200 bg-white p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-xl font-semibold tracking-tight text-slate-900">
                {experiment.title}
              </h2>
              <StatusBadge status={experiment.status} />
            </div>
            <p className="mt-1 text-sm text-slate-500">
              Created {formatDateTime(experiment.created_at)} · Updated{' '}
              {formatDateTime(experiment.updated_at)}
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <a
              href={`#${editExperimentPath(experiment.id)}`}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
            >
              <PencilIcon className="size-4" />
              Edit
            </a>
            <button
              type="button"
              onClick={() => {
                setConfirmOpen(true)
                setDeleteError(null)
              }}
              className="inline-flex items-center gap-1.5 rounded-md border border-rose-200 bg-white px-3 py-1.5 text-sm font-medium text-rose-700 shadow-sm hover:bg-rose-50"
            >
              <TrashIcon className="size-4" />
              Delete
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-3">
        <div className="flex flex-col gap-6 xl:col-span-2">
          <Card title="Hypothesis">
            <p className="whitespace-pre-line text-sm text-slate-700">
              {experiment.hypothesis}
            </p>
          </Card>
          <Card title="Target audience">
            <p className="whitespace-pre-line text-sm text-slate-700">
              {experiment.target_audience}
            </p>
          </Card>
          <Card title="Success metric">
            <p className="whitespace-pre-line text-sm text-slate-700">
              {experiment.success_metric}
            </p>
          </Card>
          <Card title="Execution steps">
            {experiment.execution_steps.length === 0 ? (
              <p className="text-sm text-slate-500">No execution steps recorded.</p>
            ) : (
              <ol
                data-testid="execution-steps"
                className="list-decimal space-y-1.5 pl-5 text-sm text-slate-700"
              >
                {experiment.execution_steps.map((step, index) => (
                  <li key={index}>{step}</li>
                ))}
              </ol>
            )}
          </Card>
          <section className="rounded-lg border border-slate-200 bg-white p-5">
            <h2 className="text-sm font-medium text-slate-500">Actual result</h2>
            {experiment.actual_result ? (
              <p className="mt-2 whitespace-pre-line text-sm text-slate-700">
                {experiment.actual_result}
              </p>
            ) : (
              <p className="mt-2 text-sm italic text-slate-400">Not recorded yet.</p>
            )}
            <form
              className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-start"
              onSubmit={(event) => {
                event.preventDefault()
                void handleSaveResult()
              }}
            >
              <div className="grow">
                <label htmlFor="actual-result-input" className="sr-only">
                  Actual result
                </label>
                <textarea
                  id="actual-result-input"
                  rows={3}
                  className={inputClass(Boolean(resultError))}
                  value={resultDraft}
                  onChange={(event) => {
                    setResultDraftOverride(event.target.value)
                    setResultError(null)
                  }}
                  placeholder="What actually happened?"
                  aria-invalid={Boolean(resultError) || undefined}
                />
                {resultError && (
                  <p role="alert" className="mt-1 text-sm text-rose-600">
                    {resultError}
                  </p>
                )}
              </div>
              <button
                type="submit"
                disabled={savingResult}
                className="inline-flex h-fit shrink-0 items-center gap-1.5 rounded-md border border-indigo-200 bg-white px-3 py-1.5 text-sm font-medium text-indigo-700 shadow-sm hover:bg-indigo-50 disabled:opacity-50"
              >
                {savingResult
                  ? 'Saving…'
                  : experiment.actual_result
                    ? 'Update result'
                    : 'Record result'}
              </button>
            </form>
          </section>
        </div>

        <div className="flex flex-col gap-6">
          <Card title="Status">
            <StatusBadge status={experiment.status} />
            <div className="mt-4">
              <label htmlFor="status-select" className="text-sm font-medium text-slate-700">
                Change status
              </label>
              <select
                id="status-select"
                value={experiment.status}
                onChange={(event) =>
                  void handleStatusChange(event.target.value as ExperimentStatus)
                }
                disabled={savingStatus}
                className={`${inputClass()} mt-1.5`}
              >
                {EXPERIMENT_STATUSES.map((statusValue) => (
                  <option key={statusValue} value={statusValue}>
                    {statusLabel(statusValue)}
                  </option>
                ))}
              </select>
              {savingStatus && <p className="mt-1.5 text-xs text-slate-500">Saving…</p>}
              {statusError && (
                <p role="alert" className="mt-1.5 text-sm text-rose-600">
                  {statusError}
                </p>
              )}
            </div>
          </Card>
          <Card title="Details">
            <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-1">
              <div>
                <dt className="text-sm font-medium text-slate-500">Channel</dt>
                <dd className="mt-0.5 text-sm text-slate-900">{experiment.channel}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-slate-500">Budget</dt>
                <dd className="mt-0.5 text-sm text-slate-900">
                  {formatBudget(experiment.budget_amount, experiment.currency_code)}
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-slate-500">Currency</dt>
                <dd className="mt-0.5 text-sm text-slate-900">{experiment.currency_code}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-slate-500">Created</dt>
                <dd className="mt-0.5 text-sm text-slate-900" title={experiment.created_at}>
                  {formatDateTime(experiment.created_at)}
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-slate-500">Updated</dt>
                <dd className="mt-0.5 text-sm text-slate-900" title={experiment.updated_at}>
                  {formatDateTime(experiment.updated_at)}
                </dd>
              </div>
            </dl>
          </Card>
        </div>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="Delete experiment"
        message={`This permanently deletes “${experiment.title}” and all of its data. This action cannot be undone.`}
        confirmLabel="Delete experiment"
        busy={deleting}
        error={deleteError}
        onConfirm={() => void handleDelete()}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  )
}
