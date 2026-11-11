import { expect, test as base } from '@playwright/test'

export const test = base.extend({
  page: async ({ page }, providePage) => {
    const password = process.env.GROWTHLOOP_E2E_OWNER_PASSWORD
    if (!password) throw new Error('Playwright owner password was not initialized')

    await page.goto('/')
    await page.getByLabel('Owner password').fill(password)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
    await providePage(page)
  },
})

export { expect }
