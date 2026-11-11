import { useCallback, useState } from 'react'

import { Pagination } from '../components/Pagination'
import { StatusBadge } from '../components/StatusBadge'
import { EmptyState, ErrorState, ListSkeleton } from '../components/states'
import { inputClass } from '../lib/ui'
import {
  EXPERIMENT_STATUSES,
  listExperiments,
  type ExperimentStatus,
} from '../lib/api'
import { formatBudget, formatDate, statusLabel } from '../lib/format'
import { experimentPath } from '../lib/router'
import { useAsyncData } from '../lib/useAsyncData'

const PAGE_SIZE = 10

export function ExperimentsPage() {
  const [statusFilter, setStatusFilter] = useState<ExperimentStatus | ''>('')
  const [page, setPage] = useState(1)

  const load = useCallback(
    () =>
      listExperiments({
        status: statusFilter === '' ? undefined : statusFilter,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      }),
    [statusFilter, page],
  )
  const { status, data, message, reload } = useAsyncData(load, [statusFilter, page])

  const handleFilterChange = (value: ExperimentStatus | '') => {
    setStatusFilter(value)
    setPage(1)
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="status-filter" className="text-sm font-medium text-slate-700">
          Status
        </label>
        <select
          id="status-filter"
          value={statusFilter}
          onChange={(event) => handleFilterChange(event.target.value as ExperimentStatus | '')}
          className={`${inputClass()} w-44`}
        >
          <option value="">All statuses</option>
          {EXPERIMENT_STATUSES.map((statusValue) => (
            <option key={statusValue} value={statusValue}>
              {statusLabel(statusValue)}
            </option>
          ))}
        </select>
        {data && (
          <p className="ml-auto text-sm text-slate-500">
            {data.total} {data.total === 1 ? 'experiment' : 'experiments'}
          </p>
        )}
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        {status === 'loading' && <ListSkeleton rows={PAGE_SIZE} />}
        {status === 'error' && (
          <div className="p-4">
            <ErrorState message={message} onRetry={reload} />
          </div>
        )}
        {status === 'ready' && data && (
          <>
            {data.total === 0 ? (
              statusFilter === '' ? (
                <EmptyState
                  title="No experiments yet"
                  description="Create your first experiment, or let Claude create one through MCP — everything shows up here."
                  action={
                    <a
                      href="#/experiments/new"
                      className="mt-1 inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-500"
                    >
                      Create experiment
                    </a>
                  }
                />
              ) : (
                <EmptyState
                  title={`No ${statusLabel(statusFilter).toLowerCase()} experiments`}
                  description="No experiments match this status filter right now."
                  action={
                    <button
                      type="button"
                      onClick={() => handleFilterChange('')}
                      className="mt-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
                    >
                      Clear filter
                    </button>
                  }
                />
              )
            ) : (
              <>
                <table className="hidden w-full text-left text-sm md:table">
                  <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th scope="col" className="px-4 py-3 font-medium">
                        Experiment
                      </th>
                      <th scope="col" className="px-4 py-3 font-medium">
                        Status
                      </th>
                      <th scope="col" className="px-4 py-3 font-medium">
                        Channel
                      </th>
                      <th scope="col" className="px-4 py-3 font-medium">
                        Budget
                      </th>
                      <th scope="col" className="px-4 py-3 font-medium">
                        Created
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.items.map((experiment) => (
                      <tr
                        key={experiment.id}
                        data-testid="experiment-row"
                        className="hover:bg-slate-50"
                      >
                        <td className="max-w-72 px-4 py-3">
                          <a
                            href={`#${experimentPath(experiment.id)}`}
                            className="font-medium text-slate-900 hover:text-indigo-600"
                          >
                            {experiment.title}
                          </a>
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={experiment.status} />
                        </td>
                        <td className="px-4 py-3 text-slate-600">{experiment.channel}</td>
                        <td className="px-4 py-3 text-slate-600">
                          {formatBudget(experiment.budget_amount, experiment.currency_code)}
                        </td>
                        <td className="px-4 py-3 text-slate-600">
                          {formatDate(experiment.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                <ul className="divide-y divide-slate-100 md:hidden">
                  {data.items.map((experiment) => (
                    <li
                      key={experiment.id}
                      data-testid="experiment-card"
                      className="p-4"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <a
                          href={`#${experimentPath(experiment.id)}`}
                          className="font-medium text-slate-900 hover:text-indigo-600"
                        >
                          {experiment.title}
                        </a>
                        <StatusBadge status={experiment.status} />
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        {experiment.channel} ·{' '}
                        {formatBudget(experiment.budget_amount, experiment.currency_code)} ·{' '}
                        {formatDate(experiment.created_at)}
                      </p>
                    </li>
                  ))}
                </ul>

                <Pagination
                  page={page}
                  pageSize={PAGE_SIZE}
                  total={data.total}
                  onChange={setPage}
                />
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
