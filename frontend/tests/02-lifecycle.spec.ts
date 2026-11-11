import { expect, test } from './fixtures'

import { deleteAllExperiments } from './helpers'

let experimentId = ''

test.describe.serial('experiment lifecycle', () => {
  test.beforeAll(async () => {
    await deleteAllExperiments()
  })

  test('creating an experiment opens its detail page', async ({ page }) => {
    await page.goto('/#/experiments/new')
    await page.getByLabel('Title').fill('Lifecycle experiment')
    await page
      .getByLabel('Hypothesis')
      .fill('Founders invite teammates when sharing is one click away')
    await page.getByLabel('Target audience').fill('Solo founders evaluating the product')
    await page.getByLabel('Channel').fill('in_app')
    await page.getByLabel('Budget').fill('15000.50')
    await page.getByLabel('Currency').fill('eur')
    await page.getByLabel('Success metric').fill('Invites sent per active user')
    await page.getByRole('button', { name: 'Add step' }).click()
    await page.getByLabel('Execution step 1').fill('Design the share dialog')
    await page.getByRole('button', { name: 'Add step' }).click()
    await page.getByLabel('Execution step 2').fill('Instrument invite analytics')
    // Reordering: moving the second step up swaps the two.
    await page.getByRole('button', { name: 'Move step 2 up' }).click()
    await expect(page.getByLabel('Execution step 1')).toHaveValue('Instrument invite analytics')
    await expect(page.getByLabel('Execution step 2')).toHaveValue('Design the share dialog')
    await page.getByRole('button', { name: 'Create experiment' }).click()
    await page.waitForURL(/#\/experiments\/[0-9a-f-]+$/)
    experimentId = page.url().split('/').pop() ?? ''

    await expect(page.getByRole('heading', { name: 'Lifecycle experiment' })).toBeVisible()
    await expect(page.getByTestId('status-badge').first()).toHaveText('Draft')
    await expect(page.getByText('€15,000.50')).toBeVisible()
    await expect(
      page.getByText('Founders invite teammates when sharing is one click away'),
    ).toBeVisible()
    await expect(page.getByText('Solo founders evaluating the product')).toBeVisible()
    await expect(page.getByText('in_app')).toBeVisible()
    await expect(page.getByText('Invites sent per active user')).toBeVisible()
    const steps = page.getByTestId('execution-steps').getByRole('listitem')
    await expect(steps).toHaveCount(2)
    await expect(steps.nth(0)).toHaveText('Instrument invite analytics')
    await expect(steps.nth(1)).toHaveText('Design the share dialog')
    await expect(page.getByText('Not recorded yet.')).toBeVisible()
  })

  test('editing updates fields and can clear optional ones', async ({ page }) => {
    await page.goto('/#/experiments')
    await page.getByRole('link', { name: 'Lifecycle experiment' }).click()
    await page.waitForURL(new RegExp(`#/experiments/${experimentId}$`))
    await page.getByRole('link', { name: 'Edit' }).click()
    await expect(page.getByLabel('Title')).toHaveValue('Lifecycle experiment')
    await expect(page.getByLabel('Budget')).toHaveValue('15000.50')
    await expect(page.getByLabel('Currency')).toHaveValue('EUR')

    await page.getByLabel('Title').fill('Lifecycle experiment (revised)')
    await page.getByLabel('Budget').fill('')
    await page.getByLabel('Execution step 1').fill('Instrument invite analytics v2')
    await page.getByRole('button', { name: 'Remove step 2' }).click()
    await page.getByRole('button', { name: 'Save changes' }).click()
    await page.waitForURL(new RegExp(`#/experiments/${experimentId}$`))

    await expect(page.getByRole('heading', { name: 'Lifecycle experiment (revised)' })).toBeVisible()
    await expect(page.getByText('No budget')).toBeVisible()
    const steps = page.getByTestId('execution-steps').getByRole('listitem')
    await expect(steps).toHaveCount(1)
    await expect(steps.nth(0)).toHaveText('Instrument invite analytics v2')
  })

  test('changing status updates the badge', async ({ page }) => {
    await page.goto(`/#/experiments/${experimentId}`)
    await expect(page.getByTestId('status-badge').first()).toHaveText('Draft')
    await page.getByLabel('Change status').selectOption('running')
    await expect(page.getByTestId('status-badge').first()).toHaveText('Running')
    await page.getByLabel('Change status').selectOption('completed')
    await expect(page.getByTestId('status-badge').first()).toHaveText('Completed')
  })

  test('recording and updating the actual result', async ({ page }) => {
    await page.goto(`/#/experiments/${experimentId}`)
    await expect(page.getByText('Not recorded yet.')).toBeVisible()
    await page.getByLabel('Actual result').fill('Invites rose 18% week over week')
    await page.getByRole('button', { name: 'Record result' }).click()
    await expect(page.getByText('Invites rose 18% week over week', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Update result' })).toBeVisible()
    await page.getByLabel('Actual result').fill('Invites rose 18%; retention flat')
    await page.getByRole('button', { name: 'Update result' }).click()
    await expect(page.getByText('Invites rose 18%; retention flat', { exact: true })).toBeVisible()
  })

  test('deleting requires explicit confirmation', async ({ page }) => {
    await page.goto(`/#/experiments/${experimentId}`)
    await page.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByText('This action cannot be undone.')).toBeVisible()
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(
      page.getByRole('heading', { name: 'Lifecycle experiment (revised)' }),
    ).toBeVisible()

    await page.getByRole('button', { name: 'Delete', exact: true }).click()
    await page.getByRole('button', { name: 'Delete experiment' }).click()
    await page.waitForURL(/#\/experiments$/)
    await expect(page.getByText('No experiments yet')).toBeVisible()
  })
})
