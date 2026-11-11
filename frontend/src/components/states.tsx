import type { ReactNode } from 'react'

import { ExclamationIcon, InboxIcon, RefreshIcon } from './icons'

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div
      role="status"
      className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500"
    >
      <span
        className="size-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600"
        aria-hidden="true"
      />
      {label}
    </div>
  )
}

/** Shimmering placeholder rows for the experiments table. */
export function ListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading experiments" className="p-4">
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          className="flex items-center gap-4 border-b border-slate-100 py-3.5 last:border-0"
        >
          <div className="h-4 w-2/5 animate-pulse rounded bg-slate-200" />
          <div className="h-4 w-14 animate-pulse rounded bg-slate-100" />
          <div className="h-4 w-20 animate-pulse rounded bg-slate-100" />
          <div className="ml-auto h-4 w-16 animate-pulse rounded bg-slate-100" />
        </div>
      ))}
    </div>
  )
}

/** Placeholder blocks for the overview stat cards. */
export function StatSkeleton() {
  return (
    <div role="status" aria-label="Loading dashboard" className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="rounded-lg border border-slate-200 bg-white p-5">
            <div className="h-4 w-24 animate-pulse rounded bg-slate-200" />
            <div className="mt-3 h-8 w-12 animate-pulse rounded bg-slate-100" />
          </div>
        ))}
      </div>
      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="h-4 w-36 animate-pulse rounded bg-slate-200 px-5 py-4" />
        {Array.from({ length: 4 }, (_, index) => (
          <div
            key={index}
            className="flex items-center gap-4 border-t border-slate-100 px-5 py-3.5"
          >
            <div className="h-4 w-1/3 animate-pulse rounded bg-slate-100" />
            <div className="ml-auto h-4 w-14 animate-pulse rounded bg-slate-100" />
          </div>
        ))}
      </div>
    </div>
  )
}

interface ErrorStateProps {
  title?: string
  message: string
  onRetry?: () => void
}

export function ErrorState({ title = 'Something went wrong', message, onRetry }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-lg border border-slate-200 bg-white px-6 py-12 text-center"
    >
      <ExclamationIcon className="size-8 text-rose-500" />
      <div>
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        <p className="mt-1 text-sm text-slate-500">{message}</p>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
        >
          <RefreshIcon className="size-4" />
          Try again
        </button>
      )}
    </div>
  )
}

interface EmptyStateProps {
  title: string
  description?: string
  action?: ReactNode
  /** "boxed" draws its own dashed card; "plain" fits inside a parent card. */
  variant?: 'boxed' | 'plain'
}

export function EmptyState({ title, description, action, variant = 'boxed' }: EmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center gap-3 px-6 py-12 text-center ${
        variant === 'boxed' ? 'rounded-lg border border-dashed border-slate-300 bg-white' : ''
      }`}
    >
      <InboxIcon className="size-8 text-slate-400" />
      <h3 className="text-base font-semibold text-slate-900">{title}</h3>
      {description && <p className="max-w-sm text-sm text-slate-500">{description}</p>}
      {action}
    </div>
  )
}
