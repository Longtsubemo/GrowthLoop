import { useEffect, useState } from 'react'

import { AppLayout, NewExperimentButton } from './components/AppLayout'
import { ExperimentCreatePage } from './pages/ExperimentCreatePage'
import { ExperimentDetailPage } from './pages/ExperimentDetailPage'
import { ExperimentEditPage } from './pages/ExperimentEditPage'
import { ExperimentsPage } from './pages/ExperimentsPage'
import { OverviewPage } from './pages/OverviewPage'
import { LoginPage } from './pages/LoginPage'
import {
  getOwnerSession,
  loginOwner,
  logoutOwner,
  type OwnerSession,
} from './lib/api'
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
  const [session, setSession] = useState<OwnerSession | null>(null)
  const [checkingSession, setCheckingSession] = useState(true)

  useEffect(() => {
    let active = true
    const expireSession = () => setSession(null)
    window.addEventListener('growthloop:auth-expired', expireSession)
    getOwnerSession()
      .then((current) => {
        if (active) setSession(current.authenticated ? current : null)
      })
      .catch(() => {
        if (active) setSession(null)
      })
      .finally(() => {
        if (active) setCheckingSession(false)
      })
    return () => {
      active = false
      window.removeEventListener('growthloop:auth-expired', expireSession)
    }
  }, [])

  if (checkingSession) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 text-sm text-slate-500">
        Checking your session…
      </main>
    )
  }

  if (!session) {
    return (
      <LoginPage
        onLogin={async (password) => {
          const authenticated = await loginOwner(password)
          setSession(authenticated)
        }}
      />
    )
  }

  async function handleLogout() {
    try {
      await logoutOwner()
    } finally {
      setSession(null)
    }
  }
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
      onLogout={handleLogout}
    >
      {renderPage(route)}
    </AppLayout>
  )
}

export default App
