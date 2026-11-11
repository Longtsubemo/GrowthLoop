import { expect, test } from '@playwright/test'

import { createExperiment, deleteAllExperiments } from './helpers'
import { runMcp } from './mcp'

/**
 * Bidirectional integration: the dashboard (browser -> REST) and Claude
 * (MCP over stdio) operate on the same `growthloop_e2e` database.
 */
test.describe.serial('MCP and dashboard share the same experiments', () => {
  let experimentId = ''

  test.beforeAll(async () => {
    await deleteAllExperiments()
  })

  test('an MCP-created experiment appears in the dashboard', async ({ page }) => {
    const created = runMcp('create_experiment', {
      title: 'MCP referral experiment',
      hypothesis: 'A referral bonus increases invites',
      target_audience: 'Existing active users',
      channel: 'referral_program',
      success_metric: 'Invites per active user',
      budget_amount: 1500.5,
      currency_code: 'EUR',
      execution_steps: ['Design the bonus', 'Ship the invite flow'],
    })
    experimentId = String(created.id)
    expect(experimentId).toMatch(/^[0-9a-f-]{36}$/)

    await page.goto('/#/experiments')
    const row = page
      .getByTestId('experiment-row')
      .filter({ hasText: 'MCP referral experiment' })
    await expect(row).toHaveCount(1)
    await expect(row.getByText('€1,500.50')).toBeVisible()
    await expect(row.getByTestId('status-badge')).toHaveText('Draft')
    await expect(row.getByText('referral_program')).toBeVisible()

    await page.goto('/#/')
    await expect(page.getByTestId('stat-total')).toHaveText('1')
    await expect(page.getByTestId('recent-experiment')).toHaveCount(1)
    await expect(
      page.getByTestId('recent-experiment').getByRole('link'),
    ).toContainText('MCP referral experiment')

    await page.goto(`/#/experiments/${experimentId}`)
    await expect(
      page.getByRole('heading', { name: 'MCP referral experiment' }),
    ).toBeVisible()
    await expect(page.getByTestId('status-badge').first()).toHaveText('Draft')
    await expect(
      page.getByText('A referral bonus increases invites'),
    ).toBeVisible()
    await expect(page.getByText('Existing active users')).toBeVisible()
    const steps = page.getByTestId('execution-steps').getByRole('listitem')
    await expect(steps).toHaveCount(2)
    await expect(steps.nth(0)).toHaveText('Design the bonus')
    await expect(steps.nth(1)).toHaveText('Ship the invite flow')
  })

  test('dashboard edits are visible through MCP', async ({ page }) => {
    await page.goto(`/#/experiments/${experimentId}`)
    await page.getByRole('link', { name: 'Edit' }).click()
    await page.getByLabel('Title').fill('MCP referral experiment (edited)')
    await page.getByLabel('Budget').fill('2000.25')
    await page.getByRole('button', { name: 'Add step' }).click()
    await page.getByLabel('Execution step 3').fill('Measure invites')
    await page.getByRole('button', { name: 'Save changes' }).click()
    await page.waitForURL(new RegExp(`#/experiments/${experimentId}$`))
    await expect(
      page.getByRole('heading', { name: 'MCP referral experiment (edited)' }),
    ).toBeVisible()

    const fetched = runMcp('get_experiment', { experiment_id: experimentId })
    expect(fetched.title).toBe('MCP referral experiment (edited)')
    expect(fetched.budget_amount).toBe('2000.25')
    expect(fetched.execution_steps).toEqual([
      'Design the bonus',
      'Ship the invite flow',
      'Measure invites',
    ])
  })

  test('dashboard status and result are visible through MCP', async ({ page }) => {
    await page.goto(`/#/experiments/${experimentId}`)
    await page.getByLabel('Change status').selectOption('running')
    await expect(page.getByTestId('status-badge').first()).toHaveText('Running')

    await page.getByLabel('Actual result').fill('Dashboard recorded an 18% lift')
    await page.getByRole('button', { name: 'Record result' }).click()
    await expect(
      page.locator('p').filter({ hasText: 'Dashboard recorded an 18% lift' }),
    ).toHaveText('Dashboard recorded an 18% lift')

    const fetched = runMcp('get_experiment', { experiment_id: experimentId })
    expect(fetched.status).toBe('running')
    expect(fetched.actual_result).toBe('Dashboard recorded an 18% lift')
  })

  test('MCP status and result changes appear in the dashboard', async ({ page }) => {
    runMcp('update_experiment_status', {
      experiment_id: experimentId,
      status: 'completed',
    })
    runMcp('record_experiment_result', {
      experiment_id: experimentId,
      actual_result: 'MCP recorded a 22% lift',
    })

    await page.goto(`/#/experiments/${experimentId}`)
    await expect(page.getByTestId('status-badge').first()).toHaveText('Completed')
    await expect(page.getByLabel('Change status')).toHaveValue('completed')
    await expect(
      page.locator('p').filter({ hasText: 'MCP recorded a 22% lift' }),
    ).toHaveText('MCP recorded a 22% lift')
  })

  test('MCP deletion is reflected in the dashboard', async ({ page }) => {
    runMcp('delete_experiment', { experiment_id: experimentId })

    await page.goto('/#/experiments')
    await expect(page.getByText('No experiments yet')).toBeVisible()

    await page.goto(`/#/experiments/${experimentId}`)
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByText("Couldn't load experiment")).toBeVisible()
    await expect(page.getByText(/not found/i)).toBeVisible()
  })

  test('deleting an externally removed experiment shows a controlled error', async ({
    page,
  }) => {
    const record = await createExperiment({
      title: 'Externally deleted experiment',
      hypothesis: 'A concurrent delete must not crash the dashboard',
      target_audience: 'Founders',
      channel: 'email',
      success_metric: 'Signups per week',
    })

    await page.goto(`/#/experiments/${record.id}`)
    await expect(
      page.getByRole('heading', { name: 'Externally deleted experiment' }),
    ).toBeVisible()

    runMcp('delete_experiment', { experiment_id: record.id })

    await page.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('button', { name: 'Delete experiment' }).click()

    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByRole('alert')).toContainText(/not found/i)
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })
})
