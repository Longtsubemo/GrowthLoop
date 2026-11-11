import { AppLayout, NewExperimentButton } from './components/AppLayout'
import { ExperimentCreatePage } from './pages/ExperimentCreatePage'
import { ExperimentDetailPage } from './pages/ExperimentDetailPage'
import { ExperimentEditPage } from './pages/ExperimentEditPage'
import { ExperimentsPage } from './pages/ExperimentsPage'
import { OverviewPage } from './pages/OverviewPage'
import { routeKey, useRoute, type Route } from './lib/router'

const PAGE_TITLES: Record<Route['name'], string> = {
  overview: 'Overview',
  experiments: 'Experiments',
  'experiment-create': 'New experiment',
  'experiment-detail': 'Experiment details',
  'experiment-edit': 'Edit experiment',
}

function renderPage(route: Route) {
  switch (route.name) {
    case 'overview':
      return <OverviewPage />
    case 'experiments':
      return <ExperimentsPage />
    case 'experiment-create':
      return <ExperimentCreatePage />
    case 'experiment-detail':
      return <ExperimentDetailPage key={routeKey(route)} id={route.id} />
    case 'experiment-edit':
      return <ExperimentEditPage key={routeKey(route)} id={route.id} />
  }
}

function App() {
  const route = useRoute()
  // The create/edit pages are reached from this button already; hiding it
  // there avoids a second "New experiment" affordance on top of a form.
  const showNewButton =
    route.name === 'overview' ||
    route.name === 'experiments' ||
    route.name === 'experiment-detail'

  return (
    <AppLayout
      route={route}
      title={PAGE_TITLES[route.name]}
      actions={showNewButton ? <NewExperimentButton /> : undefined}
    >
      {renderPage(route)}
    </AppLayout>
  )
}

export default App
