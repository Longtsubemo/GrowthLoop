/**
 * Minimal hash-based router. Keeps the stack dependency-free: navigation is
 * plain `#/...` anchors, so links are real, focusable, middle-clickable
 * elements. Routes mirror the dashboard's pages.
 */

import { useEffect, useState } from 'react'

export type Route =
  | { name: 'overview' }
  | { name: 'experiments' }
  | { name: 'experiment-create' }
  | { name: 'experiment-detail'; id: string }
  | { name: 'experiment-edit'; id: string }

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, '')
  if (path === '' || path === '/') return { name: 'overview' }
  if (path === '/experiments') return { name: 'experiments' }
  if (path === '/experiments/new') return { name: 'experiment-create' }
  const edit = /^\/experiments\/([^/]+)\/edit$/.exec(path)
  if (edit) return { name: 'experiment-edit', id: decodeURIComponent(edit[1]) }
  const detail = /^\/experiments\/([^/]+)$/.exec(path)
  if (detail) return { name: 'experiment-detail', id: decodeURIComponent(detail[1]) }
  return { name: 'overview' }
}

/** Programmatic navigation (used after create/edit/delete actions). */
export function navigate(path: string): void {
  if (`#${path}` === window.location.hash) return
  window.location.hash = path
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))
  useEffect(() => {
    const handleHashChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])
  return route
}

/** React key for a route — forces page components to remount per target. */
export function routeKey(route: Route): string {
  return 'id' in route ? `${route.name}:${route.id}` : route.name
}

export const overviewPath = '/'
export const experimentsPath = '/experiments'
export const newExperimentPath = '/experiments/new'
export function experimentPath(id: string): string {
  return `/experiments/${id}`
}
export function editExperimentPath(id: string): string {
  return `/experiments/${id}/edit`
}
