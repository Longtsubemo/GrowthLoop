import { expect, test } from '@playwright/test'

import { createExperiment, deleteAllExperiments, listAll, seedExperiments } from './helpers'

test.describe('overview statistics', () => {
  test.beforeAll(async () => {
    await deleteAllExperiments()
    // 8 experiments: 2 draft, 1 planned, 2 running, 1 completed, 1 paused,
    // 1 cancelled.
    await seedExperiments([
      { title: 'Overview draft 01' },
      { title: 'Overview draft 02' },
      { title: 'Overview planned 01', status: 'planned' },
      { title: 'Overview running 01', status: 'running' },
      { title: 'Overview running 02', status: 'running' },
      { title: 'Overview completed 01', status: 'completed' },
      { title: 'Overview paused 01', status: 'paused' },
      { title: 'Overview cancelled 01', status: 'cancelled' },
    ])
  })

  test('shows complete counts computed from the backend data', async ({ page }) => {
    // Ground truth from the API itself.
    const all = await listAll()
    expect(all).toHaveLength(8)
    const count = (statuses: string[]) =>
      all.filter((experiment) => statuses.includes(experiment.status)).length

    await page.goto('/#/')
    await expect(page.getByTestId('stat-total')).toHaveText(String(all.length))
    await expect(page.getByTestId('stat-draft-planned')).toHaveText(
      String(count(['draft', 'planned'])),
    )
    await expect(page.getByTestId('stat-running')).toHaveText(String(count(['running'])))
    await expect(page.getByTestId('stat-completed')).toHaveText(String(count(['completed'])))
  })

  test('recent experiments list the newest first and link to details', async ({ page }) => {
    await page.goto('/#/')
    const recent = page.getByTestId('recent-experiment')
    await expect(recent).toHaveCount(6)
    await expect(recent.nth(0).getByRole('link')).toContainText('Overview cancelled 01')
    await recent.nth(0).getByRole('link').click()
    await page.waitForURL(/#\/experiments\/[0-9a-f-]+$/)
    await expect(page.getByRole('heading', { name: 'Overview cancelled 01' })).toBeVisible()
    await expect(page.getByTestId('status-badge').first()).toHaveText('Cancelled')
  })
})

test.describe('overview with more than one page of experiments', () => {
  test.beforeAll(async () => {
    await deleteAllExperiments()
    // 101 experiments: the list endpoint caps at 100 per page, so the
    // overview must follow pagination to compute complete counts.
    for (let index = 0; index < 101; index += 1) {
      await createExperiment({
        title: `Bulk experiment ${String(index + 1).padStart(3, '0')}`,
        hypothesis: 'Bulk seeding hypothesis for the overview page',
        target_audience: 'Founders',
        channel: 'email',
        success_metric: 'Signups per week',
      })
    }
  })

  test('counts every experiment across pages', async ({ page }) => {
    const all = await listAll()
    expect(all.length).toBeGreaterThan(100)
    await page.goto('/#/')
    await expect(page.getByTestId('stat-total')).toHaveText(String(all.length))
    // All bulk experiments are drafts.
    await expect(page.getByTestId('stat-draft-planned')).toHaveText(String(all.length))
    await expect(page.getByTestId('stat-running')).toHaveText('0')
    await expect(page.getByTestId('stat-completed')).toHaveText('0')
    await expect(page.getByTestId('recent-experiment')).toHaveCount(6)
  })
})
