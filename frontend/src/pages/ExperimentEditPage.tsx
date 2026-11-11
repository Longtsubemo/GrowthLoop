import { ExperimentForm } from '../components/ExperimentForm'
import { ErrorState, Spinner } from '../components/states'
import {
  getExperiment,
  updateExperiment,
  type ExperimentSubmitPayload,
} from '../lib/api'
import { experimentPath, navigate } from '../lib/router'
import { useAsyncData } from '../lib/useAsyncData'

export function ExperimentEditPage({ id }: { id: string }) {
  const { status, data, message, reload } = useAsyncData(() => getExperiment(id), [id])

  if (status === 'loading') return <Spinner label="Loading experiment…" />
  if (status === 'error') return <ErrorState message={message} onRetry={reload} />

  const handleSubmit = async (payload: ExperimentSubmitPayload) => {
    const updated = await updateExperiment(id, payload)
    navigate(experimentPath(updated.id))
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <p className="truncate text-sm text-slate-500">
        Editing “{data.title}”. Empty optional fields clear the stored values.
      </p>
      <ExperimentForm
        initial={data}
        submitLabel="Save changes"
        onSubmit={handleSubmit}
        onCancel={() => navigate(experimentPath(id))}
      />
    </div>
  )
}
