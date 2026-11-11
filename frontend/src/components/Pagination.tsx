import { ChevronLeftIcon, ChevronRightIcon } from './icons'

interface PaginationProps {
  page: number
  pageSize: number
  /** Total number of records across all pages. */
  total: number
  onChange: (page: number) => void
}

export function Pagination({ page, pageSize, total, onChange }: PaginationProps) {
  if (total === 0) return null
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const from = (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)
  const buttonClass =
    'inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40'

  return (
    <nav
      className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3"
      aria-label="Pagination"
    >
      <p className="text-sm text-slate-500">
        Showing{' '}
        <span className="font-medium text-slate-700">{from}</span>–
        <span className="font-medium text-slate-700">{to}</span> of{' '}
        <span className="font-medium text-slate-700">{total}</span>
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          className={buttonClass}
          aria-label="Previous page"
        >
          <ChevronLeftIcon className="size-4" />
          Previous
        </button>
        <span className="text-sm text-slate-500" aria-live="polite">
          Page {page} of {totalPages}
        </span>
        <button
          type="button"
          onClick={() => onChange(page + 1)}
          disabled={page >= totalPages}
          className={buttonClass}
          aria-label="Next page"
        >
          Next
          <ChevronRightIcon className="size-4" />
        </button>
      </div>
    </nav>
  )
}
