/**
 * Display formatting helpers. Budget amounts arrive from the API as decimal
 * strings ("15000.50"); they are parsed only for display, and forms always
 * submit the raw string so precision is never lost.
 */

import type { ExperimentStatus } from './api'

const dateFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })
const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

export function formatDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : dateFormatter.format(date)
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : dateTimeFormatter.format(date)
}

/**
 * Format a budget with its currency code. The backend accepts any
 * three-letter code, not just ISO currencies, so fall back to
 * "CODE amount" when Intl does not recognize the code.
 */
export function formatBudget(amount: string | null, currencyCode: string): string {
  if (amount === null) return 'No budget'
  const value = Number(amount)
  if (Number.isNaN(value)) return `${currencyCode} ${amount}`
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: currencyCode,
    }).format(value)
  } catch {
    return `${currencyCode} ${new Intl.NumberFormat(undefined).format(value)}`
  }
}

/** Human label for an experiment status ("draft" → "Draft"). */
export function statusLabel(status: ExperimentStatus): string {
  return status.charAt(0).toUpperCase() + status.slice(1)
}
