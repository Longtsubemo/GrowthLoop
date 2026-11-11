import { expect, test } from './fixtures'

import { createExperiment, deleteAllExperiments } from './helpers'

test.describe('empty states, loading, errors and form validation', () => {
  test.beforeAll(async () => {
    await deleteAllExperiments()
  })

  test('experiments list shows an empty state with a create action', async ({ page }) => {
    await page.goto('/#/experiments')
    await expect(page.getByText('No experiments yet')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Create experiment' })).toBeVisible()
    await expect(page.getByLabel('Status')).toHaveValue('')
  })

  test('overview shows zero counts and an empty recent list', async ({ page }) => {
    await page.goto('/#/')
    await expect(page.getByTestId('stat-total')).toHaveText('0')
    await expect(page.getByTestId('stat-draft-planned')).toHaveText('0')
    await expect(page.getByTestId('stat-running')).toHaveText('0')
    await expect(page.getByTestId('stat-completed')).toHaveText('0')
    await expect(page.getByText('No experiments yet')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Create experiment' })).toBeVisible()
  })

  test('experiments list renders a loading skeleton before the data', async ({ page }) => {
    await page.route('**/api/v1/experiments*', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      await route.continue()
    })
    await page.goto('/#/experiments')
    await expect(page.getByRole('status', { name: 'Loading experiments' })).toBeVisible()
    // The delayed request still resolves against the real backend.
    await expect(page.getByText('No experiments yet')).toBeVisible()
  })

  test('overview renders a loading skeleton before the data', async ({ page }) => {
    await page.route('**/api/v1/experiments*', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      await route.continue()
    })
    await page.goto('/#/')
    await expect(page.getByRole('status', { name: 'Loading dashboard' })).toBeVisible()
    await expect(page.getByTestId('stat-total')).toHaveText('0')
  })

  test('experiments list shows an error state and recovers on retry', async ({ page }) => {
    await createExperiment({
      title: 'Retry recovery experiment',
      hypothesis: 'The list should reappear after clicking retry',
      target_audience: 'Founders',
      channel: 'email',
      success_metric: 'Open rate',
    })
    await page.route('**/api/v1/experiments*', (route) => route.abort())
    await page.goto('/#/experiments')
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByText('Something went wrong')).toBeVisible()
    await expect(
      page.getByText('Could not reach the GrowthLoop server. Is the backend running?'),
    ).toBeVisible()
    await page.unroute('**/api/v1/experiments*')
    await page.getByRole('button', { name: 'Try again' }).click()
    await expect(page.getByRole('link', { name: 'Retry recovery experiment' })).toBeVisible()
  })

  test('create form validates required fields, budget, currency and blank steps', async ({
    page,
  }) => {
    await page.goto('/#/experiments/new')
    await page.getByRole('button', { name: 'Add step' }).click()
    await page.getByRole('button', { name: 'Create experiment' }).click()

    await expect(page.getByText('Title is required.')).toBeVisible()
    await expect(page.getByText('Hypothesis is required.')).toBeVisible()
    await expect(page.getByText('Target audience is required.')).toBeVisible()
    await expect(page.getByText('Channel is required.')).toBeVisible()
    await expect(page.getByText('Success metric is required.')).toBeVisible()
    await expect(page.getByText('Step cannot be empty.')).toBeVisible()

    await page.getByLabel('Budget').fill('12.345')
    await page.getByLabel('Currency').fill('EU')
    await page.getByRole('button', { name: 'Create experiment' }).click()
    await expect(
      page.getByText('Budget must be a non-negative number with up to 2 decimal places.'),
    ).toBeVisible()
    await expect(
      page.getByText('Currency must be a 3-letter code such as INR or USD.'),
    ).toBeVisible()

    // Fixing a field clears its error immediately.
    await page.getByLabel('Title').fill('Client validated experiment')
    await page.getByRole('button', { name: 'Create experiment' }).click()
    await expect(page.getByText('Title is required.')).toHaveCount(0)
  })

  test('create form renders backend field errors from a 422 response', async ({ page }) => {
    // Mocked supplement: verifies field-error rendering for a server-side
    // rejection (the real backend accepts this payload, so it is intercepted).
    await page.route('**/api/v1/experiments', async (route) => {
      await route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: [
            {
              type: 'string_too_short',
              loc: ['body', 'title'],
              msg: 'String should have at least 1 character',
              input: '',
            },
          ],
        }),
      })
    })
    await page.goto('/#/experiments/new')
    await page.getByLabel('Title').fill('Server rejected experiment')
    await page.getByLabel('Hypothesis').fill('A hypothesis the mock will reject')
    await page.getByLabel('Target audience').fill('Founders')
    await page.getByLabel('Channel').fill('email')
    await page.getByLabel('Success metric').fill('Open rate')
    await page.getByRole('button', { name: 'Create experiment' }).click()
    await expect(
      page.getByText('The server rejected some fields. Please fix them and try again.'),
    ).toBeVisible()
    await expect(page.getByText('String should have at least 1 character')).toBeVisible()
    await page.unroute('**/api/v1/experiments')
  })
})
