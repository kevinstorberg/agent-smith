import { describe, expect, it } from 'vitest';
import { COOKIE_MAX_AGE, MAX_COOKIE_BYTES, MAX_VIEW_ENTRIES, VIEW_COOKIE_NAME, cookieBytes, defaultView, mergeViewCookie, readViewCookie, resolveView } from '../viewPreferences';

describe('view preference cookie boundary', () => {
  it('normalizes restored action item sorting against the selected status before requests', () => {
    for (const [status, sort] of [['open', 'manual'], ['completed', 'completed'], ['all', 'newest']] as const) {
      expect(resolveView('actionItems', '', new URLSearchParams({ status, sort: status === 'open' ? 'completed' : 'manual' })).sort).toBe(sort);
    }
    const cookie = mergeViewCookie('', 'actionItems', { ...defaultView('actionItems'), status: 'completed', sort: 'title' });
    expect(resolveView('actionItems', cookie, new URLSearchParams())).toMatchObject({ status: 'completed', sort: 'title' });
    expect(resolveView('actionItems', cookie, new URLSearchParams('status=open&sort=')).sort).toBe('manual');
  });

  it('stores only nondefaults, preserves other cookies, and emits the complete host-only attribute budget', () => {
    const value = mergeViewCookie('other=keep', 'jobs', { ...defaultView('jobs'), q: 'release', sort: 'name', limit: 25, offset: 50 }, { secure: true });
    expect(value).toContain(`; Path=/; SameSite=Lax; Max-Age=${COOKIE_MAX_AGE}; Secure`);
    expect(value).not.toContain('Domain=');
    expect(value).not.toContain('other=');
    expect(readViewCookie(`other=keep; ${value.split(';')[0]}`)).toEqual([{ key: 'jobs', values: { q: 'release', sort: 'name', limit: 25, offset: 50 } }]);
    expect(resolveView('jobs', value, new URLSearchParams())).toEqual({ q: 'release', schedule_enabled: '', sort: 'name', limit: 25, offset: 50 });
    expect(cookieBytes(value)).toBeLessThanOrEqual(MAX_COOKIE_BYTES);
  });

  it.each(['', '%broken', 'null', encodeURIComponent('{"v":2,"views":[]}'), encodeURIComponent('{"v":1,"views":"bad"}'), 'x'.repeat(3001)])('recovers safely from malformed cookie %s', value => {
    expect(readViewCookie(`${VIEW_COOKIE_NAME}=${value}`)).toEqual([]);
  });

  it('drops unknown fields, invalid scopes, and invalid settings without retaining a stale partial query', () => {
    const data = { v: 1, views: [
      { key: 'unknown', values: { q: 'old' } }, { key: 'jobs', scope: '../bad', values: { q: 'old' } },
      { key: 'jobs', values: { q: 'old', sort: 'injected' } }, { key: 'plans', values: { draft: 'private' } },
    ] };
    expect(readViewCookie(`${VIEW_COOKIE_NAME}=${encodeURIComponent(JSON.stringify(data))}`)).toEqual([]);
  });

  it('gives explicit URL presence precedence, including clears and invalid enum/page values', () => {
    const cookie = mergeViewCookie('', 'jobs', { ...defaultView('jobs'), q: 'old', sort: 'name', schedule_enabled: 'false', limit: 25, offset: 50 });
    expect(resolveView('jobs', cookie, new URLSearchParams('q=&sort=bad&schedule_enabled=&limit=999&offset=-10'))).toEqual(defaultView('jobs'));
    expect(resolveView('jobs', cookie, new URLSearchParams('q=new'))).toMatchObject({ q: 'new', offset: 0, limit: 25 });
    expect(resolveView('jobs', cookie, new URLSearchParams('q=new&offset=75'))).toMatchObject({ q: 'new', offset: 75 });
    expect(resolveView('jobs', cookie, new URLSearchParams('limit=25&offset=29'))).toMatchObject({ limit: 25, offset: 25 });
  });

  it('isolates resources/scopes and bounds the recency list to twelve entries', () => {
    let cookie = '';
    for (let scope = 1; scope <= MAX_VIEW_ENTRIES + 1; scope++) cookie = mergeViewCookie(cookie, 'jobs', { ...defaultView('jobs'), q: `scope${scope}` }, { scope: String(scope) });
    expect(readViewCookie(cookie)).toHaveLength(12);
    expect(readViewCookie(cookie)[0].scope).toBe('13');
    expect(resolveView('jobs', cookie, new URLSearchParams(), '1')).toEqual(defaultView('jobs'));
    expect(resolveView('jobs', cookie, new URLSearchParams(), '2').q).toBe('scope2');
    expect(resolveView('plans', cookie, new URLSearchParams(), '2')).toEqual(defaultView('plans'));
    cookie = mergeViewCookie(cookie, 'jobs', { ...defaultView('jobs'), q: 'scope2' }, { scope: '2' });
    expect(readViewCookie(cookie)[0].scope).toBe('2');
  });

  it('measures ASCII and Unicode worksheet bytes after encoding, evicting before the whole cookie exceeds 3000', () => {
    const cases = [['plain search and tags', 2493, 12], ['é'.repeat(100), 2421, 3], ['漢字🙂'.repeat(45), 1625, 1]] as const;
    for (const [q, expectedBytes, expectedEntries] of cases) {
      let cookie = '';
      for (let scope = 1; scope <= 12; scope++) cookie = mergeViewCookie(cookie, 'plans', { ...defaultView('plans'), q, project: 'agent-smith', limit: 50, offset: 100 }, { scope: String(scope), secure: true });
      const bytes = cookieBytes(cookie);
      expect([...cookie].every(character => character.charCodeAt(0) <= 127)).toBe(true);
      expect(bytes).toBe(cookie.length);
      expect(bytes).toBeLessThanOrEqual(3000);
      expect(bytes).toBe(expectedBytes);
      expect(readViewCookie(cookie)[0].values.q).toBe(q);
      expect(readViewCookie(cookie)).toHaveLength(expectedEntries);
    }
  });

  it('omits an oversized current entry and removes its old saved query without changing live values or other entries', () => {
    let cookie = mergeViewCookie('', 'jobs', { ...defaultView('jobs'), q: 'obsolete' });
    cookie = mergeViewCookie(cookie, 'plans', { ...defaultView('plans'), q: 'keep' });
    const live = { ...defaultView('jobs'), q: '🙂'.repeat(300) };
    cookie = mergeViewCookie(cookie, 'jobs', live);
    expect(live.q).toBe('🙂'.repeat(300));
    expect(readViewCookie(cookie)).toEqual([{ key: 'plans', values: { q: 'keep' } }]);
    expect(cookieBytes(cookie)).toBeLessThanOrEqual(3000);
  });

  it('resets only the requested view and preserves the latest entries supplied by another writer', () => {
    const first = mergeViewCookie('', 'jobs', { ...defaultView('jobs'), q: 'jobs' });
    const second = mergeViewCookie(first, 'plans', { ...defaultView('plans'), q: 'plans' });
    const reset = mergeViewCookie(second, 'jobs', defaultView('jobs'));
    expect(readViewCookie(reset)).toEqual([{ key: 'plans', values: { q: 'plans' } }]);
  });
});
