import { readdirSync } from 'node:fs';
import { relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test as base, expect, type Request } from '@playwright/test';
import { pageGeometry } from './geometry';

interface APIRequest { url: URL; request: Request }
type ResponseFactory = (request: APIRequest) => unknown | Promise<unknown>;
interface NetworkEntry { method: string; url: string; disposition: string }
interface OfflineAPI {
  get(path: string, response: unknown | ResponseFactory): void;
  expectBlocked(method: string, url: string): void;
  requests: NetworkEntry[];
}

const dist = fileURLToPath(new URL('../dist/', import.meta.url));
const assets = new Set(readdirSync(dist, { recursive: true, withFileTypes: true })
  .filter(entry => entry.isFile())
  .map(entry => `/${relative(dist, resolve(entry.parentPath, entry.name)).split(sep).join('/')}`));

export const test = base.extend<{ fixtureAPI: OfflineAPI }>({
  fixtureAPI: async ({ context, baseURL }, provide, testInfo) => {
    if (!baseURL) throw new Error('Offline browser tests require the owned preview base URL');
    const origin = new URL(baseURL).origin;
    const routes = new Map<string, ResponseFactory>();
    const requests: NetworkEntry[] = [];
    const violations: NetworkEntry[] = [];
    const expectedBlocks = new Set<string>();
    const blocked = (method: string, url: string) => {
      const entry = { method, url, disposition: 'blocked' };
      requests.push(entry);
      if (!expectedBlocks.delete(`${method} ${url}`)) violations.push(entry);
    };
    await context.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== origin || request.method() !== 'GET') {
        blocked(request.method(), request.url());
        await route.abort('blockedbyclient');
        return;
      }
      if (url.pathname === '/api' || url.pathname.startsWith('/api/')) {
        const factory = routes.get(url.pathname);
        if (!factory) {
          blocked('GET', request.url());
          await route.abort('blockedbyclient');
          return;
        }
        requests.push({ method: 'GET', url: request.url(), disposition: 'fixture' });
        await route.fulfill({ json: await factory({ url, request }) });
        return;
      }
      if (!request.isNavigationRequest() && !assets.has(url.pathname)) {
        blocked('GET', request.url());
        await route.abort('blockedbyclient');
        return;
      }
      requests.push({ method: 'GET', url: request.url(), disposition: 'preview' });
      await route.continue();
    });
    await context.routeWebSocket('**/*', socket => {
      blocked('WEBSOCKET', socket.url());
      socket.close({ code: 1008, reason: 'Offline browser tests forbid WebSockets' });
    });
    try {
      await provide({
        get(path, response) {
          if (!path.startsWith('/api/') || path.includes('?')) throw new Error('Register one exact API pathname without query parameters');
          routes.set(path, typeof response === 'function' ? response as ResponseFactory : () => structuredClone(response));
        },
        expectBlocked(method, url) { expectedBlocks.add(`${method} ${url}`); },
        requests,
      });
    } finally {
      await context.close();
      await testInfo.attach('offline-network.json', { body: JSON.stringify(requests, null, 2), contentType: 'application/json' });
      expect(violations, 'Every API request must have an explicit fixture; external requests and writes are forbidden').toEqual([]);
      expect([...expectedBlocks], 'Expected network rejections must actually be exercised').toEqual([]);
    }
  },
  page: async ({ context, fixtureAPI }, provide, testInfo) => {
    void fixtureAPI;
    const page = await context.newPage();
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    try { await provide(page); }
    finally {
      if (!page.isClosed()) {
        await testInfo.attach('page-geometry.json', { body: JSON.stringify(await pageGeometry(page), null, 2), contentType: 'application/json' });
      }
      expect(errors, 'Real browser rendering must not throw application errors').toEqual([]);
    }
  },
});

export { expect };
