import { createHash, randomBytes } from 'node:crypto'
import { createServer } from 'node:http'

import { expect, test } from '@playwright/test'

import { BACKEND_ORIGIN } from './e2e-env'

test('consent POST can follow its 303 to the registered OAuth callback', async ({
  page,
  request,
}) => {
  const password = process.env.GROWTHLOOP_E2E_OWNER_PASSWORD
  if (!password) throw new Error('Playwright owner password was not initialized')

  let callbackCount = 0
  let callbackHasExpectedParameters = false
  const callbackServer = createServer((incoming, outgoing) => {
    callbackCount += 1
    const callback = new URL(incoming.url ?? '/', 'http://127.0.0.1')
    callbackHasExpectedParameters =
      callback.searchParams.has('code') &&
      callback.searchParams.get('state') === 'browser-csp-regression-state' &&
      callback.searchParams.get('iss') === BACKEND_ORIGIN
    outgoing.writeHead(200, { 'Content-Type': 'text/html' })
    outgoing.end('<!doctype html><title>Callback reached</title><p>Callback reached</p>')
  })
  await new Promise<void>((resolve, reject) => {
    callbackServer.once('error', reject)
    callbackServer.listen(0, '127.0.0.1', resolve)
  })
  try {
    const callbackAddress = callbackServer.address()
    if (!callbackAddress || typeof callbackAddress === 'string') {
      throw new Error('OAuth callback test server did not bind to a TCP port')
    }
    const redirectUri = `http://127.0.0.1:${callbackAddress.port}/oauth/callback`
    const verifier = randomBytes(32).toString('base64url')
    const challenge = createHash('sha256').update(verifier).digest('base64url')
    const registration = await request.post(`${BACKEND_ORIGIN}/register`, {
      data: {
        client_name: 'Claude',
        redirect_uris: [redirectUri],
        grant_types: ['authorization_code', 'refresh_token'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
        scope: 'experiments',
      },
    })
    expect(registration.status()).toBe(201)
    const client = (await registration.json()) as { client_id: string }

    const authorization = new URLSearchParams({
      response_type: 'code',
      client_id: client.client_id,
      redirect_uri: redirectUri,
      code_challenge: challenge,
      code_challenge_method: 'S256',
      state: 'browser-csp-regression-state',
      scope: 'experiments',
      resource: `${BACKEND_ORIGIN}/mcp`,
    })
    const authorizationResponse = await request.get(
      `${BACKEND_ORIGIN}/authorize?${authorization.toString()}`,
      { maxRedirects: 0 },
    )
    expect(authorizationResponse.status()).toBe(302)
    const consentUrl = new URL(
      authorizationResponse.headers()['location'],
      BACKEND_ORIGIN,
    )

    const consoleErrors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })

    const consentResponse = await page.goto(consentUrl.toString())
    expect(consentResponse?.status()).toBe(200)
    const csp = consentResponse?.headers()['content-security-policy'] ?? ''
    expect(csp).toContain(`form-action 'self' http://127.0.0.1:${callbackAddress.port}`)
    expect(await page.locator('form').getAttribute('action')).toMatch(/^\?request_id=/)

    await page.getByLabel('Owner password').fill(password)
    await page.getByRole('button', { name: 'Sign in and review' }).click()
    await expect(page.getByRole('button', { name: 'Allow access' })).toBeVisible()
    await page.getByRole('button', { name: 'Allow access' }).click()

    await expect(page.getByText('Callback reached')).toBeVisible()
    expect(callbackCount).toBe(1)
    expect(callbackHasExpectedParameters).toBe(true)
    expect(consoleErrors.filter((message) => message.includes('form-action'))).toEqual([])
  } finally {
    await new Promise<void>((resolve, reject) => {
      callbackServer.close((error) => (error ? reject(error) : resolve()))
    })
  }
})
