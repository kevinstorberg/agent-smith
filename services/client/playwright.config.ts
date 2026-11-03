import { createServer } from 'node:net';
import { defineConfig } from '@playwright/test';

async function previewPort(): Promise<number> {
  const inherited = process.env.AGENT_SMITH_BROWSER_PORT;
  if (inherited !== undefined) {
    const port = Number(inherited);
    if (!Number.isSafeInteger(port) || port < 1 || port > 65535 || port === 7654) {
      throw new Error('Browser preview requires a unique, nondefault loopback port');
    }
    return port;
  }
  const reservation = createServer();
  await new Promise<void>((resolve, reject) => {
    reservation.once('error', reject);
    reservation.listen(0, '127.0.0.1', resolve);
  });
  const address = reservation.address();
  await new Promise<void>((resolve, reject) => reservation.close(error => error ? reject(error) : resolve()));
  if (!address || typeof address === 'string' || address.port === 7654) {
    throw new Error('Browser preview requires a unique loopback port');
  }
  // Playwright evaluates this configuration again in each worker process.
  process.env.AGENT_SMITH_BROWSER_PORT = String(address.port);
  return address.port;
}
const port = await previewPort();
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './browser-tests',
  testMatch: '**/*.spec.ts',
  timeout: 15_000,
  expect: { timeout: 5_000 },
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    browserName: 'chromium',
    serviceWorkers: 'block',
    reducedMotion: 'reduce',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    actionTimeout: 5_000,
    navigationTimeout: 10_000,
  },
  projects: [1440, 1024, 390, 320].map(width => ({
    name: `chromium-${width}`,
    use: { viewport: { width, height: 900 } },
  })),
  webServer: {
    command: `node browser-tests/preview.mjs ${port}`,
    url: baseURL,
    timeout: 30_000,
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 5_000 },
    env: { AGENT_SMITH_AUTOMATED_TESTS: '1' },
  },
});
