import type { ExperimentStatus } from '../lib/api'
import { statusLabel } from '../lib/format'

const BADGE_STYLES: Record<ExperimentStatus, string> = {
  draft: 'bg-slate-100 text-slate-600 ring-slate-500/20',
  planned: 'bg-sky-50 text-sky-700 ring-sky-600/20',
  running: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  completed: 'bg-indigo-50 text-indigo-700 ring-indigo-600/20',
  paused: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  cancelled: 'bg-rose-50 text-rose-700 ring-rose-600/20',
}

export function StatusBadge({ status }: { status: ExperimentStatus }) {
  return (
    <span
      data-testid="status-badge"
      className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${BADGE_STYLES[status]}`}
    >
      {statusLabel(status)}
    </span>
  )
}
