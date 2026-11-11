import { expect, test } from '@playwright/test'

test('owner login restores the session after refresh and logout clears it', async ({ page }) => {
  const password = process.env.GROWTHLOOP_E2E_OWNER_PASSWORD
  if (!password) throw new Error('Playwright owner password was not initialized')

  await page.goto('/')
  await expect(page.getByLabel('Owner password')).toBeVisible()
  await page.getByLabel('Owner password').fill('incorrect password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toContainText('Invalid credentials')

  await page.getByLabel('Owner password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()

  const cookies = await page.context().cookies()
  const sessionCookie = cookies.find((cookie) => cookie.name === 'growthloop_session')
  expect(sessionCookie?.httpOnly).toBe(true)
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])

  await page.reload()
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByLabel('Owner password')).toBeVisible()
  expect(
    (await page.context().cookies()).some((cookie) => cookie.name === 'growthloop_session'),
  ).toBe(false)
})
