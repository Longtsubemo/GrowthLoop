import { ExperimentForm } from '../components/ExperimentForm'
import { createExperiment, type ExperimentSubmitPayload } from '../lib/api'
import { experimentPath, experimentsPath, navigate } from '../lib/router'

export function ExperimentCreatePage() {
  const handleSubmit = async (payload: ExperimentSubmitPayload) => {
    const created = await createExperiment(payload)
    navigate(experimentPath(created.id))
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <p className="text-sm text-slate-500">
        Describe the experiment below. It is saved to PostgreSQL immediately and
        is visible to Claude through MCP as soon as it exists.
      </p>
      <ExperimentForm
        submitLabel="Create experiment"
        onSubmit={handleSubmit}
        onCancel={() => navigate(experimentsPath)}
      />
    </div>
  )
}
