import type { ReactNode } from 'react'

import type { Route } from '../lib/router'
import { BeakerIcon, ChartIcon, PlusIcon } from './icons'

interface AppLayoutProps {
  route: Route
  title: string
  actions?: ReactNode
  onLogout: () => void
  children: ReactNode
}

const NAV_ITEMS = [
  {
    path: '/',
    label: 'Overview',
    icon: ChartIcon,
    isActive: (route: Route) => route.name === 'overview',
  },
  {
    path: '/experiments',
    label: 'Experiments',
    icon: BeakerIcon,
    isActive: (route: Route) => route.name !== 'overview',
  },
]

/** Primary "Create experiment" action shown in the header. */
export function NewExperimentButton() {
  return (
    <a
      href="#/experiments/new"
      className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-500"
    >
      <PlusIcon className="size-4" />
      New experiment
    </a>
  )
}

/**
 * Application shell: fixed sidebar navigation on desktop, a top header
 * (with brand and horizontal nav on mobile), and the main content area.
 */
export function AppLayout({ route, title, actions, onLogout, children }: AppLayoutProps) {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-slate-200 bg-white lg:flex">
        <div className="flex h-16 items-center gap-2.5 border-b border-slate-200 px-6">
          <span className="flex size-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
            G
          </span>
          <span className="text-lg font-semibold tracking-tight">GrowthLoop</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3" aria-label="Main">
          {NAV_ITEMS.map((item) => {
            const active = item.isActive(route)
            return (
              <a
                key={item.path}
                href={`#${item.path}`}
                aria-current={active ? 'page' : undefined}
                className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium ${
                  active
                    ? 'bg-indigo-50 text-indigo-700'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                }`}
              >
                <item.icon className="size-5" />
                {item.label}
              </a>
            )
          })}
        </nav>
        <div className="border-t border-slate-200 px-5 py-4">
          <p className="text-xs leading-5 text-slate-400">
            Experiments can also be managed by Claude through a configured MCP
            connection. Changes remain reviewable here.
          </p>
        </div>
      </aside>

      <div className="flex min-h-screen flex-col lg:pl-64">
        <header className="sticky top-0 z-30 border-b border-slate-200 bg-white">
          <div className="flex h-14 items-center justify-between gap-3 px-4 sm:px-6 lg:h-16 lg:px-8">
            <a href="#/" className="flex items-center gap-2 lg:hidden">
              <span className="flex size-7 items-center justify-center rounded-md bg-indigo-600 text-xs font-bold text-white">
                G
              </span>
              <span className="font-semibold tracking-tight">GrowthLoop</span>
            </a>
            <h1 className="hidden text-lg font-semibold tracking-tight text-slate-900 lg:block">
              {title}
            </h1>
            <div className="ml-auto flex items-center gap-2">
              {actions}
              <button
                className="rounded-md px-2 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                onClick={onLogout}
                type="button"
              >
                Sign out
              </button>
            </div>
          </div>
          <nav
            className="flex gap-1 border-t border-slate-100 px-3 py-1.5 lg:hidden"
            aria-label="Main"
          >
            {NAV_ITEMS.map((item) => {
              const active = item.isActive(route)
              return (
                <a
                  key={item.path}
                  href={`#${item.path}`}
                  aria-current={active ? 'page' : undefined}
                  className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-medium ${
                    active ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600'
                  }`}
                >
                  <item.icon className="size-4" />
                  {item.label}
                </a>
              )
            })}
          </nav>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 lg:px-8">
          {children}
        </main>
      </div>
    </div>
  )
}
