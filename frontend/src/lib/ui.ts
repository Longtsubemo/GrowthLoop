/** Shared class strings for form controls (kept out of component files). */

/**
 * Shared input styling. Pass a truthy value when the field has a
 * validation error so the border and focus ring turn red.
 */
export function inputClass(hasError?: boolean): string {
  return [
    'w-full rounded-md border px-3 py-2 text-sm text-slate-900 shadow-sm placeholder:text-slate-400',
    'focus:outline-none focus:ring-2 disabled:cursor-not-allowed disabled:bg-slate-50',
    hasError
      ? 'border-rose-300 focus:border-rose-500 focus:ring-rose-500/30'
      : 'border-slate-300 focus:border-indigo-500 focus:ring-indigo-500/30',
  ].join(' ')
}
