import { expect, test } from '@playwright/test'

test('dashboard shell renders navigation and the overview page', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
  await expect(page.locator('aside').getByRole('link', { name: 'Experiments' })).toBeVisible()
  await expect(page.locator('aside').getByRole('link', { name: 'Overview' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'New experiment' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Recent experiments' })).toBeVisible()
})
