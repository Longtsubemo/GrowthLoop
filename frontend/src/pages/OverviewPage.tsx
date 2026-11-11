import type { ComponentType, SVGProps } from 'react'

import { StatusBadge } from '../components/StatusBadge'
import { BeakerIcon, CheckCircleIcon, DocumentIcon, PlayIcon } from '../components/icons'
import { EmptyState, ErrorState, StatSkeleton } from '../components/states'
import { listExperiments, type Experiment, type ExperimentStatus } from '../lib/api'
import { formatBudget, formatDate } from '../lib/format'
import { experimentPath } from '../lib/router'
import { useAsyncData } from '../lib/useAsyncData'

/**
 * The list endpoint paginates (max 100 per page), so the overview fetches
 * every page and computes the summary counts from the complete set of
 * records — a single page would silently under-count. The loop ends when
 * the accumulated records reach the reported total or a page comes back
 * empty (data changed underneath us).
 */
const FETCH_PAGE_SIZE = 100

async function loadOverview(): Promise<{ experiments: Experiment[]; total: number }> {
  const experiments: Experiment[] = []
  let offset = 0
  let total: number | null = null
  for (let guard = 0; guard < 1000; guard += 1) {
    const page = await listExperiments({ limit: FETCH_PAGE_SIZE, offset })
    if (total === null) total = page.total
    experiments.push(...page.items)
    if (page.items.length === 0) break
    offset += page.items.length
    if (experiments.length >= total) break
  }
  return { experiments, total: total ?? experiments.length }
}

function countByStatus(experiments: Experiment[], statuses: ExperimentStatus[]): number {
  return experiments.filter((experiment) => statuses.includes(experiment.status)).length
}

interface StatCardProps {
  label: string
  value: number
  testId: string
  icon: ComponentType<SVGProps<SVGSVGElement>>
}

function StatCard({ label, value, testId, icon: Icon }: StatCardProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-500">{label}</p>
        <Icon className="size-5 text-slate-400" />
      </div>
      <p data-testid={testId} className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">
        {value}
      </p>
    </div>
  )
}

export function OverviewPage() {
  const { status, data, message, reload } = useAsyncData(loadOverview, [])

  if (status === 'loading') return <StatSkeleton />
  if (status === 'error') return <ErrorState message={message} onRetry={reload} />

  const { experiments, total } = data
  const cards: StatCardProps[] = [
    { label: 'Total experiments', value: total, testId: 'stat-total', icon: BeakerIcon },
    {
      label: 'Draft or planned',
      value: countByStatus(experiments, ['draft', 'planned']),
      testId: 'stat-draft-planned',
      icon: DocumentIcon,
    },
    {
      label: 'Running',
      value: countByStatus(experiments, ['running']),
      testId: 'stat-running',
      icon: PlayIcon,
    },
    {
      label: 'Completed',
      value: countByStatus(experiments, ['completed']),
      testId: 'stat-completed',
      icon: CheckCircleIcon,
    },
  ]

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => (
          <StatCard key={card.testId} {...card} />
        ))}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">Recent experiments</h2>
          <a
            href="#/experiments"
            className="text-sm font-medium text-indigo-600 hover:text-indigo-500"
          >
            View all
          </a>
        </div>
        {experiments.length === 0 ? (
          <EmptyState
            variant="plain"
            title="No experiments yet"
            description="Create your first experiment to start tracking growth."
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
          <ul className="divide-y divide-slate-100">
            {experiments.slice(0, 6).map((experiment) => (
              <li key={experiment.id} data-testid="recent-experiment">
                <a
                  href={`#${experimentPath(experiment.id)}`}
                  className="flex items-center gap-4 px-5 py-3.5 hover:bg-slate-50"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-slate-900">
                      {experiment.title}
                    </p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {experiment.channel} · {formatBudget(experiment.budget_amount, experiment.currency_code)} ·{' '}
                      {formatDate(experiment.created_at)}
                    </p>
                  </div>
                  <StatusBadge status={experiment.status} />
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
