import { readdirSync } from 'node:fs';
import { relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test as base, expect, type Request } from '@playwright/test';
import { pageGeometry } from './geometry';

export interface APIRequest { url: URL; request: Request }
type ResponseFactory = (request: APIRequest) => unknown | Promise<unknown>;
interface NetworkEntry { method: string; url: string; disposition: string }
type FixtureMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
interface OfflineAPI {
  get(path: string, response: unknown | ResponseFactory, status?: number): void;
  mock(method: FixtureMethod, path: string, response: unknown | ResponseFactory, status?: number): void;
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
    const routes = new Map<string, { factory: ResponseFactory; status: number }>();
    const register = (method: FixtureMethod, path: string, response: unknown | ResponseFactory, status = 200) => {
      if (!path.startsWith('/api/') || path.includes('?')) throw new Error('Register one exact API pathname without query parameters');
      routes.set(`${method} ${path}`, { factory: typeof response === 'function' ? response as ResponseFactory : () => structuredClone(response), status });
    };
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
      if (url.origin !== origin) {
        blocked(request.method(), request.url());
        await route.abort('blockedbyclient');
        return;
      }
      if (url.pathname === '/api' || url.pathname.startsWith('/api/')) {
        const fixture = routes.get(`${request.method()} ${url.pathname}`);
        if (!fixture) {
          blocked(request.method(), request.url());
          await route.abort('blockedbyclient');
          return;
        }
        requests.push({ method: request.method(), url: request.url(), disposition: 'fixture' });
        await route.fulfill({ json: await fixture.factory({ url, request }), status: fixture.status });
        return;
      }
      if (request.method() !== 'GET' || (!request.isNavigationRequest() && !assets.has(url.pathname))) {
        blocked(request.method(), request.url());
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
        get(path, response, status) { register('GET', path, response, status); },
        mock: register,
        expectBlocked(method, url) { expectedBlocks.add(`${method} ${url}`); },
        requests,
      });
    } finally {
      await context.close();
      await testInfo.attach('offline-network.json', { body: JSON.stringify(requests, null, 2), contentType: 'application/json' });
      expect(violations, 'Every API request requires an explicit fixture; external requests and unregistered writes are forbidden').toEqual([]);
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
