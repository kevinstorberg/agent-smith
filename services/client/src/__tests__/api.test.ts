import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api } from '../api';

function mockFetch(body: unknown, options: { ok?: boolean; status?: number; statusText?: string } = {}) {
  const { ok = true, status = 200, statusText = 'OK' } = options;
  return vi.fn().mockResolvedValue({
    ok,
    status,
    statusText,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(body ? JSON.stringify(body) : ''),
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('parseError (tested through api methods)', () => {
  it('throws string detail from error response', async () => {
    globalThis.fetch = mockFetch({ detail: 'Not found' }, { ok: false, status: 404, statusText: 'Not Found' });
    await expect(api.plans.get(999)).rejects.toThrow('Not found');
  });

  it('joins array detail (FastAPI validation format)', async () => {
    globalThis.fetch = mockFetch(
      { detail: [{ loc: ['body', 'name'], msg: 'field required' }] },
      { ok: false, status: 422, statusText: 'Unprocessable Entity' },
    );
    await expect(api.plans.get(1)).rejects.toThrow('name: field required');
  });

  it('falls back to status text when no detail', async () => {
    globalThis.fetch = mockFetch({}, { ok: false, status: 500, statusText: 'Internal Server Error' });
    await expect(api.plans.get(1)).rejects.toThrow('500 Internal Server Error');
  });

  it('falls back to status text when body is not JSON', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      statusText: 'Bad Gateway',
      json: () => Promise.reject(new Error('not json')),
    });
    await expect(api.plans.get(1)).rejects.toThrow('502 Bad Gateway');
  });
});

describe('GET requests', () => {
  it('constructs correct URL with path', async () => {
    globalThis.fetch = mockFetch({ id: 1, title: 'test' });
    await api.plans.get(42);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(url).toContain('/api/plans/42');
  });

  it('appends query params', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    await api.harness.items.list('rule', { limit: 5, offset: 10, name: 'test' });
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(url).toContain('limit=5');
    expect(url).toContain('offset=10');
    expect(url).toContain('name=test');
  });

  it('skips falsy query params', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    await api.harness.items.list('rule', { limit: 10, offset: 0, name: '' });
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(url).not.toContain('name=');
  });
});

describe('POST requests', () => {
  it('sends JSON body with correct headers', async () => {
    globalThis.fetch = mockFetch({ id: 1 });
    await api.plans.create({ title: 'Test', body: 'Content' });
    const [, opts] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(opts.method).toBe('POST');
    expect(opts.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(opts.body)).toEqual({ title: 'Test', body: 'Content' });
  });
});

describe('PUT requests', () => {
  it('sends PUT method', async () => {
    globalThis.fetch = mockFetch({ id: 1 });
    await api.plans.update(1, { title: 'Updated' });
    const [, opts] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(opts.method).toBe('PUT');
  });
});

describe('PATCH requests', () => {
  it('sends PATCH method', async () => {
    globalThis.fetch = mockFetch({ id: 1, enabled: false });
    await api.harness.items.updateMetadata('rule', 1, { enabled: false });
    const [, opts] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(opts.method).toBe('PATCH');
  });
});

describe('DELETE requests', () => {
  it('sends DELETE method', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(''),
    });
    await api.plans.remove(1);
    const [, opts] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(opts.method).toBe('DELETE');
  });

  it('handles empty response body', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(''),
    });
    const result = await api.plans.remove(1);
    expect(result).toBeUndefined();
  });

  it('parses JSON response when present', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('{"deleted":true,"id":1}'),
    });
    const result = await api.memory.remove('abc-123');
    expect(result).toEqual({ deleted: true, id: 1 });
  });
});

describe('paginationToParams (tested through api methods)', () => {
  it('serializes limit and offset', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    await api.plans.list({ limit: 25, offset: 50 });
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(url).toContain('limit=25');
    expect(url).toContain('offset=50');
  });

  it('omits undefined pagination params', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    await api.plans.list({});
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(url).not.toContain('limit=');
    expect(url).not.toContain('offset=');
  });
});

describe('specific API methods', () => {
  it('harness.sync sends POST to /harness/sync', async () => {
    globalThis.fetch = mockFetch({ success: true, stdout: '', stderr: '' });
    await api.harness.sync();
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(url).toBe('/api/harness/sync');
  });

  it('memory.search includes q param', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    await api.memory.search('test query', { limit: 10, offset: 0 });
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(url).toContain('q=test+query');
  });

  it('harness.items.configs.add sends POST', async () => {
    globalThis.fetch = mockFetch({ id: 5 });
    await api.harness.items.configs.add('rule', 1, { device: 'work' });
    const [url, opts] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe('/api/harness/items/rule/1/configs');
    expect(opts.method).toBe('POST');
  });
});
