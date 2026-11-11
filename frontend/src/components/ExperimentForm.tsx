import { useState, type FormEvent } from 'react'

import {
  toApiError,
  type Experiment,
  type ExperimentSubmitPayload,
} from '../lib/api'
import { inputClass } from '../lib/ui'
import { Field } from './Field'
import {
  ArrowDownIcon,
  ArrowUpIcon,
  PlusIcon,
  TrashIcon,
} from './icons'

interface ExperimentFormProps {
  /** Existing experiment when editing; omitted when creating. */
  initial?: Experiment
  submitLabel: string
  /** Shown on the submit button while the request is in flight. */
  submittingLabel?: string
  /** Resolve on success (the page navigates away); throw to show an error. */
  onSubmit: (payload: ExperimentSubmitPayload) => Promise<void>
  onCancel: () => void
}

interface FormValues {
  title: string
  hypothesis: string
  targetAudience: string
  channel: string
  budgetAmount: string
  currencyCode: string
  executionSteps: string[]
  successMetric: string
  actualResult: string
}

type FormErrors = Record<string, string>

// Mirrors the backend rules for usability only; the API stays the source of
// truth. Up to 10 integer digits plus 2 decimals keeps the total within the
// backend's max_digits=12 / decimal_places=2.
const BUDGET_PATTERN = /^\d{1,10}(\.\d{1,2})?$/
const CURRENCY_PATTERN = /^[A-Za-z]{3}$/

function initialValues(initial?: Experiment): FormValues {
  return {
    title: initial?.title ?? '',
    hypothesis: initial?.hypothesis ?? '',
    targetAudience: initial?.target_audience ?? '',
    channel: initial?.channel ?? '',
    budgetAmount: initial?.budget_amount ?? '',
    currencyCode: initial?.currency_code ?? 'INR',
    executionSteps: initial?.execution_steps ?? [],
    successMetric: initial?.success_metric ?? '',
    actualResult: initial?.actual_result ?? '',
  }
}

function validate(values: FormValues): FormErrors {
  const errors: FormErrors = {}
  const title = values.title.trim()
  const channel = values.channel.trim()
  const budget = values.budgetAmount.trim()
  const currency = values.currencyCode.trim()

  if (!title) errors.title = 'Title is required.'
  else if (title.length > 200)
    errors.title = 'Title must be 200 characters or fewer.'

  if (!values.hypothesis.trim())
    errors.hypothesis = 'Hypothesis is required.'
  if (!values.targetAudience.trim())
    errors.target_audience = 'Target audience is required.'

  if (!channel) errors.channel = 'Channel is required.'
  else if (channel.length > 50)
    errors.channel = 'Channel must be 50 characters or fewer.'

  if (!values.successMetric.trim())
    errors.success_metric = 'Success metric is required.'

  if (!currency) errors.currency_code = 'Currency is required.'
  else if (!CURRENCY_PATTERN.test(currency))
    errors.currency_code =
      'Currency must be a 3-letter code such as INR or USD.'

  if (budget && !BUDGET_PATTERN.test(budget))
    errors.budget_amount =
      'Budget must be a non-negative number with up to 2 decimal places.'

  values.executionSteps.forEach((step, index) => {
    if (!step.trim()) errors[`step-${index}`] = 'Step cannot be empty.'
  })

  return errors
}

/**
 * Reusable create/edit form. Decimal values stay strings end-to-end so the
 * exact budget the user typed is what the API receives.
 */
export function ExperimentForm({
  initial,
  submitLabel,
  submittingLabel = 'Saving…',
  onSubmit,
  onCancel,
}: ExperimentFormProps) {
  const [values, setValues] = useState<FormValues>(() => initialValues(initial))
  const [errors, setErrors] = useState<FormErrors>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const isEditing = initial !== undefined

  function clearError(key: string) {
    setErrors((previous) => {
      if (!(key in previous)) return previous
      const next = { ...previous }
      delete next[key]
      return next
    })
  }

  function setField<K extends keyof FormValues>(
    field: K,
    value: FormValues[K],
  ) {
    setValues((previous) => ({ ...previous, [field]: value }))
    clearError(String(field))
  }

  function updateStep(index: number, value: string) {
    setValues((previous) => {
      const executionSteps = [...previous.executionSteps]
      executionSteps[index] = value
      return { ...previous, executionSteps }
    })
    clearError(`step-${index}`)
  }

  function addStep() {
    setValues((previous) => ({
      ...previous,
      executionSteps: [...previous.executionSteps, ''],
    }))
  }

  function removeStep(index: number) {
    setValues((previous) => ({
      ...previous,
      executionSteps: previous.executionSteps.filter(
        (_, position) => position !== index,
      ),
    }))
    setErrors((previous) => {
      const next: FormErrors = {}
      for (const [key, message] of Object.entries(previous)) {
        if (!key.startsWith('step-')) next[key] = message
      }
      return next
    })
  }

  function moveStep(index: number, direction: -1 | 1) {
    setValues((previous) => {
      const target = index + direction
      if (target < 0 || target >= previous.executionSteps.length) {
        return previous
      }
      const executionSteps = [...previous.executionSteps]
      ;[executionSteps[index], executionSteps[target]] = [
        executionSteps[target],
        executionSteps[index],
      ]
      return { ...previous, executionSteps }
    })
    setErrors((previous) => {
      const next: FormErrors = {}
      for (const [key, message] of Object.entries(previous)) {
        if (!key.startsWith('step-')) next[key] = message
      }
      return next
    })
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const nextErrors = validate(values)
    setErrors(nextErrors)
    setFormError(null)
    if (Object.keys(nextErrors).length > 0) return

    const payload: ExperimentSubmitPayload = {
      title: values.title.trim(),
      hypothesis: values.hypothesis.trim(),
      target_audience: values.targetAudience.trim(),
      channel: values.channel.trim(),
      budget_amount:
        values.budgetAmount.trim() === '' ? null : values.budgetAmount.trim(),
      currency_code: values.currencyCode.trim().toUpperCase(),
      execution_steps: values.executionSteps
        .map((step) => step.trim())
        .filter((step) => step !== ''),
      success_metric: values.successMetric.trim(),
      actual_result:
        values.actualResult.trim() === ''
          ? null
          : values.actualResult.trim(),
    }

    setSubmitting(true)
    try {
      await onSubmit(payload)
    } catch (error) {
      const info = toApiError(error)
      setFormError(info.message)
      const fieldErrors: FormErrors = {}
      for (const [key, message] of Object.entries(info.fieldErrors)) {
        const nestedStep = /^execution_steps\.(\d+)$/.exec(key)
        fieldErrors[nestedStep ? `step-${nestedStep[1]}` : key] = message
      }
      setErrors((previous) => ({ ...previous, ...fieldErrors }))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="flex flex-col gap-6 rounded-lg border border-slate-200 bg-white p-5 sm:p-6"
    >
      {formError && (
        <div
          role="alert"
          className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
        >
          {formError}
        </div>
      )}

      <Field label="Title" htmlFor="title" error={errors.title}>
        <input
          id="title"
          value={values.title}
          onChange={(event) => setField('title', event.target.value)}
          className={inputClass(Boolean(errors.title))}
          aria-invalid={Boolean(errors.title)}
          aria-describedby={errors.title ? 'title-error' : undefined}
          placeholder="e.g. Referral bonus for first purchase"
        />
      </Field>

      <Field label="Hypothesis" htmlFor="hypothesis" error={errors.hypothesis}>
        <textarea
          id="hypothesis"
          rows={3}
          value={values.hypothesis}
          onChange={(event) => setField('hypothesis', event.target.value)}
          className={inputClass(Boolean(errors.hypothesis))}
          aria-invalid={Boolean(errors.hypothesis)}
          aria-describedby={errors.hypothesis ? 'hypothesis-error' : undefined}
          placeholder="If we…, then… because…"
        />
      </Field>

      <Field
        label="Target audience"
        htmlFor="target-audience"
        error={errors.target_audience}
      >
        <textarea
          id="target-audience"
          rows={2}
          value={values.targetAudience}
          onChange={(event) => setField('targetAudience', event.target.value)}
          className={inputClass(Boolean(errors.target_audience))}
          aria-invalid={Boolean(errors.target_audience)}
          aria-describedby={
            errors.target_audience ? 'target-audience-error' : undefined
          }
          placeholder="Who is this experiment for?"
        />
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Channel" htmlFor="channel" error={errors.channel}>
          <input
            id="channel"
            value={values.channel}
            onChange={(event) => setField('channel', event.target.value)}
            className={inputClass(Boolean(errors.channel))}
            aria-invalid={Boolean(errors.channel)}
            aria-describedby={errors.channel ? 'channel-error' : undefined}
            placeholder="e.g. paid_search"
          />
        </Field>

        <Field
          label="Success metric"
          htmlFor="success-metric"
          error={errors.success_metric}
        >
          <input
            id="success-metric"
            value={values.successMetric}
            onChange={(event) => setField('successMetric', event.target.value)}
            className={inputClass(Boolean(errors.success_metric))}
            aria-invalid={Boolean(errors.success_metric)}
            aria-describedby={
              errors.success_metric ? 'success-metric-error' : undefined
            }
            placeholder="e.g. 5% lift in conversion"
          />
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Budget"
          htmlFor="budget-amount"
          error={errors.budget_amount}
          hint="Optional. Up to 2 decimal places."
        >
          <input
            id="budget-amount"
            inputMode="decimal"
            value={values.budgetAmount}
            onChange={(event) => setField('budgetAmount', event.target.value)}
            className={inputClass(Boolean(errors.budget_amount))}
            aria-invalid={Boolean(errors.budget_amount)}
            aria-describedby={
              errors.budget_amount ? 'budget-amount-error' : 'budget-amount-hint'
            }
            placeholder="0.00"
          />
        </Field>

        <Field
          label="Currency"
          htmlFor="currency-code"
          error={errors.currency_code}
          hint="Three-letter code, e.g. INR, USD, EUR."
        >
          <input
            id="currency-code"
            value={values.currencyCode}
            onChange={(event) => setField('currencyCode', event.target.value)}
            className={inputClass(Boolean(errors.currency_code))}
            aria-invalid={Boolean(errors.currency_code)}
            aria-describedby={
              errors.currency_code ? 'currency-code-error' : 'currency-code-hint'
            }
            list="currency-codes"
            maxLength={3}
            placeholder="INR"
          />
          <datalist id="currency-codes">
            <option value="INR" />
            <option value="USD" />
            <option value="EUR" />
            <option value="GBP" />
          </datalist>
        </Field>
      </div>

      <fieldset className="flex flex-col gap-3">
        <legend className="text-sm font-medium text-slate-700">
          Execution steps
        </legend>
        <p className="text-xs text-slate-500">
          Add the steps in the order they should be executed.
        </p>

        {values.executionSteps.length === 0 && (
          <p className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-500">
            No steps yet. Add the first step to describe how the experiment
            will run.
          </p>
        )}

        {values.executionSteps.map((step, index) => {
          const error = errors[`step-${index}`]
          return (
            <div key={index} className="flex items-start gap-2">
              <span
                className="mt-2 w-6 shrink-0 text-right text-sm tabular-nums text-slate-400"
                aria-hidden="true"
              >
                {index + 1}.
              </span>
              <div className="flex-1">
                <label htmlFor={`step-${index}`} className="sr-only">
                  Execution step {index + 1}
                </label>
                <input
                  id={`step-${index}`}
                  value={step}
                  onChange={(event) => updateStep(index, event.target.value)}
                  className={inputClass(Boolean(error))}
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? `step-${index}-error` : undefined}
                  placeholder={`Step ${index + 1}`}
                />
                {error && (
                  <p
                    id={`step-${index}-error`}
                    className="mt-1 text-sm text-rose-600"
                  >
                    {error}
                  </p>
                )}
              </div>
              <div className="mt-1 flex shrink-0 items-center gap-0.5">
                <button
                  type="button"
                  onClick={() => moveStep(index, -1)}
                  disabled={index === 0}
                  className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                  aria-label={`Move step ${index + 1} up`}
                >
                  <ArrowUpIcon className="size-4" />
                </button>
                <button
                  type="button"
                  onClick={() => moveStep(index, 1)}
                  disabled={index === values.executionSteps.length - 1}
                  className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                  aria-label={`Move step ${index + 1} down`}
                >
                  <ArrowDownIcon className="size-4" />
                </button>
                <button
                  type="button"
                  onClick={() => removeStep(index)}
                  className="rounded p-1.5 text-slate-500 hover:bg-rose-50 hover:text-rose-600"
                  aria-label={`Remove step ${index + 1}`}
                >
                  <TrashIcon className="size-4" />
                </button>
              </div>
            </div>
          )
        })}

        <div>
          <button
            type="button"
            onClick={addStep}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
          >
            <PlusIcon className="size-4" />
            Add step
          </button>
        </div>
      </fieldset>

      <Field
        label="Actual result"
        htmlFor="actual-result"
        error={errors.actual_result}
        hint={
          isEditing
            ? 'Optional. Clearing this field removes the recorded result.'
            : 'Optional. Record it later once the experiment has run.'
        }
      >
        <textarea
          id="actual-result"
          rows={3}
          value={values.actualResult}
          onChange={(event) => setField('actualResult', event.target.value)}
          className={inputClass(Boolean(errors.actual_result))}
          aria-invalid={Boolean(errors.actual_result)}
          aria-describedby={
            errors.actual_result
              ? 'actual-result-error'
              : 'actual-result-hint'
          }
          placeholder="What happened?"
        />
      </Field>

      <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 pt-4">
        <button
          type="button"
          onClick={onCancel}
          disabled={submitting}
          className="rounded-md px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-500 disabled:opacity-60"
        >
          {submitting && (
            <span
              className="size-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white"
              aria-hidden="true"
            />
          )}
          {submitting ? submittingLabel : submitLabel}
        </button>
      </div>
    </form>
  )
}
