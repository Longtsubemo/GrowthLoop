import { expect, test } from '@playwright/test'

import { deleteAllExperiments, seedExperiments } from './helpers'

test.describe('experiments list, filtering and pagination', () => {
  test.beforeAll(async () => {
    await deleteAllExperiments()
    // 12 experiments: 5 draft, 3 running, 2 completed, 1 planned, 1 paused.
    // None cancelled, so the cancelled filter exercises the empty-filter state.
    await seedExperiments([
      { title: 'Filter draft 01', status: 'draft' },
      { title: 'Filter draft 02', status: 'draft' },
      { title: 'Filter draft 03', status: 'draft', channel: 'email' },
      { title: 'Filter draft 04', status: 'draft' },
      { title: 'Filter draft 05', status: 'draft' },
      { title: 'Filter running 01', status: 'running' },
      { title: 'Filter running 02', status: 'running' },
      { title: 'Filter running 03', status: 'running' },
      {
        title: 'Filter completed 01',
        status: 'completed',
        budgetAmount: '15000.50',
        currencyCode: 'EUR',
      },
      { title: 'Filter completed 02', status: 'completed' },
      { title: 'Filter planned 01', status: 'planned' },
      { title: 'Filter paused 01', status: 'paused' },
    ])
  })

  test('lists experiments with all columns and paginates', async ({ page }) => {
    await page.goto('/#/experiments')
    for (const header of ['Experiment', 'Status', 'Channel', 'Budget', 'Created']) {
      await expect(page.getByRole('columnheader', { name: header })).toBeVisible()
    }

    const rows = page.getByTestId('experiment-row')
    await expect(rows).toHaveCount(10)
    await expect(page.getByText('Showing 1–10 of 12')).toBeVisible()
    await expect(page.getByText('Page 1 of 2')).toBeVisible()
    await expect(page.getByText('12 experiments')).toBeVisible()

    // Newest first (the API orders by created_at desc); the last seed leads.
    await expect(rows.nth(0).getByRole('link')).toHaveText('Filter paused 01')
    await expect(rows.nth(3).getByText('€15,000.50')).toBeVisible()

    await page.getByRole('button', { name: 'Next page' }).click()
    await expect(rows).toHaveCount(2)
    await expect(page.getByText('Showing 11–12 of 12')).toBeVisible()
    await expect(page.getByText('Page 2 of 2')).toBeVisible()
    await expect(rows.nth(0).getByRole('link')).toHaveText('Filter draft 02')

    await page.getByRole('button', { name: 'Previous page' }).click()
    await expect(page.getByText('Showing 1–10 of 12')).toBeVisible()
    await expect(page.getByText('Page 1 of 2')).toBeVisible()
  })

  test('status filter narrows the list and can be cleared', async ({ page }) => {
    await page.goto('/#/experiments')

    await page.getByLabel('Status').selectOption('running')
    await expect(page.getByTestId('experiment-row')).toHaveCount(3)
    await expect(page.getByText('Showing 1–3 of 3')).toBeVisible()
    await expect(page.getByText('3 experiments')).toBeVisible()
    // Scope to table rows: the mobile card list renders its own badges in
    // the DOM even though it is hidden at this viewport.
    const badges = page.getByTestId('experiment-row').getByTestId('status-badge')
    await expect(badges).toHaveCount(3)
    await expect(badges.filter({ hasText: 'Running' })).toHaveCount(3)

    await page.getByLabel('Status').selectOption('paused')
    await expect(page.getByTestId('experiment-row')).toHaveCount(1)
    await expect(page.getByText('Showing 1–1 of 1')).toBeVisible()

    await page.getByLabel('Status').selectOption('cancelled')
    await expect(page.getByText('No cancelled experiments')).toBeVisible()
    await page.getByRole('button', { name: 'Clear filter' }).click()
    await expect(page.getByTestId('experiment-row')).toHaveCount(10)
    await expect(page.getByText('Showing 1–10 of 12')).toBeVisible()
  })

  test('clicking a row opens the experiment detail page', async ({ page }) => {
    await page.goto('/#/experiments')
    await page.getByRole('link', { name: 'Filter paused 01' }).click()
    await page.waitForURL(/#\/experiments\/[0-9a-f-]+$/)
    await expect(page.getByRole('heading', { name: 'Filter paused 01' })).toBeVisible()
    await expect(page.getByTestId('status-badge').first()).toHaveText('Paused')
    await expect(page.getByText('Hypothesis for Filter paused 01')).toBeVisible()
  })
})
