import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api, ApiError } from '../api';

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

describe('action items', () => {
  it('sends paging, combined filters and a bounded deadline to the real fetch boundary', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    const timeout = vi.spyOn(AbortSignal, 'timeout');
    await api.actionItems.list({ q: 'roadmap', project: 'Paralign', tags: ['product', 'growth'], status: 'open', sort: 'manual', limit: 10, offset: 20 });
    const [url, options] = vi.mocked(globalThis.fetch).mock.calls[0];
    const query = new URL(String(url)).searchParams;
    expect(query.getAll('tags')).toEqual(['product', 'growth']);
    expect(Object.fromEntries(query)).toMatchObject({ q: 'roadmap', project: 'Paralign', status: 'open', sort: 'manual', limit: '10', offset: '20' });
    expect(timeout).toHaveBeenCalledWith(30_000);
    expect(options?.signal).toBeInstanceOf(AbortSignal);
  });

  it('preserves request identity, explicit clears, revisions and a relative move anchor', async () => {
    globalThis.fetch = mockFetch({ id: 5 });
    await api.actionItems.create({ title: 'Review scope', request_id: '9d773b2b-9ab3-4a56-925e-ac41634522fa' });
    await api.actionItems.update(5, { expected_revision: 3, project: null, tags: [], description: '', status: 'completed' });
    await api.actionItems.move(5, { expected_revision: 4, after_id: 10 });
    await api.actionItems.remove(5, 5);
    const calls = vi.mocked(globalThis.fetch).mock.calls;
    expect(JSON.parse(String(calls[0][1]?.body))).toEqual({ title: 'Review scope', request_id: '9d773b2b-9ab3-4a56-925e-ac41634522fa' });
    expect(JSON.parse(String(calls[1][1]?.body))).toEqual({ expected_revision: 3, project: null, tags: [], description: '', status: 'completed' });
    expect(JSON.parse(String(calls[2][1]?.body))).toEqual({ expected_revision: 4, after_id: 10 });
    expect(JSON.parse(String(calls[3][1]?.body))).toEqual({ expected_revision: 5 });
    expect(calls[3][1]?.method).toBe('DELETE');
  });

  it('reports uncertain timeout outcomes without adding deadlines to existing job calls', async () => {
    globalThis.fetch = vi.fn().mockRejectedValueOnce(new DOMException('Timed out', 'TimeoutError')).mockImplementation(mockFetch({}));
    await expect(api.actionItems.create({ title: 'Task', request_id: '9d773b2b-9ab3-4a56-925e-ac41634522fa' })).rejects.toThrow('Refresh to check whether your change was saved');
    await api.jobs.runNow(1);
    expect(vi.mocked(globalThis.fetch).mock.calls[1][1]).not.toHaveProperty('signal');
  });

  it.each(['json', 'text', 'error'] as const)('keeps the deadline through %s response decoding after headers arrive', async kind => {
    const aborted = () => Promise.reject(new DOMException('Body stopped', 'AbortError'));
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: kind !== 'error', status: 503, statusText: 'Unavailable', json: aborted, text: aborted });
    const result = kind === 'text' ? api.actionItems.remove(5, 1) : api.actionItems.get(5);
    await expect(result).rejects.toThrow('Refresh to check whether your change was saved');
  });
});

describe('manual meeting analysis', () => {
  it('sends explicit candidate filters, frozen authorization and receipt-only Resume with 30 second deadlines', async () => {
    globalThis.fetch = mockFetch({});
    const timeout = vi.spyOn(AbortSignal, 'timeout');
    const expected = { provider: 'granola', account_key: 'work', source_name: 'work', meeting_revision: 3, transcript_hash: 'a'.repeat(64), participants_revision: 2, speaker_updated_at: null, profile_updated_at: null, memory_updated_at: null };
    const input = { request_id: 'a3b8c4d5-e678-4567-89ab-cdef01234567', confirmed: true as const, scope: 'profiles' as const, target_profile: { id: 'profile', expected_revision: 7 }, meetings: [{ id: 'meeting', expected }] };
    await api.meetingAnalysis.candidates({ profile_id: 'profile', related: false, q: 'roadmap', search_transcript: true, source: 'work', after: '2026-10-28T04:00:00.000Z', before: '2026-10-30T03:59:59.999Z', limit: 10, offset: 20 });
    await api.meetingAnalysis.request(input);
    await api.meetingAnalysis.progress(input.request_id);
    await api.meetingAnalysis.resume(input.request_id);
    const calls = vi.mocked(globalThis.fetch).mock.calls;
    expect(Object.fromEntries(new URL(String(calls[0][0])).searchParams)).toEqual({ profile_id: 'profile', related: 'false', q: 'roadmap', search_transcript: 'true', source: 'work', after: '2026-10-28T04:00:00.000Z', before: '2026-10-30T03:59:59.999Z', limit: '10', offset: '20' });
    expect(JSON.parse(String(calls[1][1]?.body))).toEqual(input);
    expect(String(calls[2][0])).toContain(`/meeting-analysis/requests/${input.request_id}`);
    expect(JSON.parse(String(calls[3][1]?.body))).toEqual({ confirmed: true });
    expect(timeout.mock.calls).toEqual([[30_000], [30_000], [30_000], [30_000]]);
    for (const [, options] of calls) expect(options?.signal).toBeInstanceOf(AbortSignal);
  });

  it.each([true, false])('keeps its deadline through success=%s JSON decoding after response headers', async ok => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok, status: 503, statusText: 'Unavailable', json: () => Promise.reject(new DOMException('Body stopped', 'AbortError')) });
    await expect(api.meetingAnalysis.progress('request')).rejects.toThrow('Refresh to check whether your change was saved');
  });

  it('reports an uncertain POST timeout and preserves existing long-running job behavior', async () => {
    globalThis.fetch = vi.fn().mockRejectedValueOnce(new DOMException('Deadline', 'TimeoutError')).mockImplementation(mockFetch({}));
    await expect(api.meetingAnalysis.resume('request')).rejects.toThrow('Refresh to check whether your change was saved');
    await api.jobs.runNow(1);
    expect(vi.mocked(globalThis.fetch).mock.calls[1][1]).not.toHaveProperty('signal');
  });
});

describe('parseError (tested through api methods)', () => {
  it('requests paged vocabulary searches and reads an exact term outside the current page', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    await api.meetings.vocabulary.list({ q: 'security', limit: 10, offset: 20 });
    await api.meetings.vocabulary.get('term/id');
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(Object.fromEntries(new URL(calls[0][0]).searchParams)).toEqual({ q: 'security', limit: '10', offset: '20' });
    expect(new URL(calls[1][0]).pathname).toBe('/api/meetings/vocabulary/term%2Fid');
  });
  it('requests scoped plan searches, graph jobs and exact executions through existing APIs', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    await api.plans.search('security', { project: 'Paralign', status: 'draft' });
    await api.jobs.forGraph('persona');
    await api.jobs.execution(42, 77);
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(Object.fromEntries(new URL(calls[0][0]).searchParams)).toEqual({ q: 'security', project: 'Paralign', status: 'draft' });
    expect(new URL(calls[1][0]).pathname).toBe('/api/jobs/graph/persona');
    expect(new URL(calls[2][0]).pathname).toBe('/api/jobs/42/executions/77');
  });

  it('preserves a conflict status for profile revision recovery', async () => {
    globalThis.fetch = mockFetch({ detail: 'Profile changed' }, { ok: false, status: 409 });
    try {
      await api.profiles.get('profile-id');
      expect.fail('Expected a conflict');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).status).toBe(409);
    }
  });
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
  it('serializes evidence filters and per-edge ownership without losing false or omitted values', async () => {
    globalThis.fetch = mockFetch({});
    await api.profiles.claims('person', { limit: 20, offset: 40, q: 'delivery date', epistemic: 'inference', category: 'perception', confidence: 'high', status: 'corrected', target_id: 'target', sort: 'newest' });
    await api.profiles.updateRelationship('person', 'edge', { expected_revision: 3, allow_agent_notes: true });
    await api.profiles.createRelationship('person', { expected_revision: 4, target_id: 'target', target_revision: 2, label: '' });
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(Object.fromEntries(new URL(calls[0][0]).searchParams)).toEqual({ limit: '20', offset: '40', q: 'delivery date', epistemic: 'inference', category: 'perception', confidence: 'high', status: 'corrected', target_id: 'target', sort: 'newest' });
    expect(JSON.parse(calls[1][1].body)).toEqual({ expected_revision: 3, allow_agent_notes: true });
    expect(JSON.parse(calls[2][1].body)).not.toHaveProperty('notes');
  });
  it('reads compact profiles and loads only the requested evidence page', async () => {
    globalThis.fetch = mockFetch({});
    await api.profiles.get('profile/id');
    await api.profiles.claims('profile/id', { limit: 20, offset: 40 });
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    const detail = new URL(calls[0][0]);
    expect(detail.pathname).toBe('/api/profiles/profile%2Fid');
    expect(Object.fromEntries(detail.searchParams)).toEqual({ include_evidence: 'false' });
    const claims = new URL(calls[1][0]);
    expect(claims.pathname).toBe('/api/profiles/profile%2Fid/claims');
    expect(Object.fromEntries(claims.searchParams)).toEqual({ limit: '20', offset: '40' });
  });
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
  it('stamps statement assignments with the captured transcript and queues explicit identification', async () => {
    globalThis.fetch = mockFetch({ status: 'queued' });
    const body = { expected_revision: 3, expected_transcript_hash: 'captured-hash', participants: [{ name: 'Alex', segment_id: 'segment-2' }] };
    await api.meetings.updateParticipants('meeting-id', body);
    await api.meetings.identifyParticipants('meeting-id');
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(JSON.parse(calls[0][1].body)).toEqual(body);
    expect(calls[0][1].method).toBe('PUT');
    expect(calls[1][0]).toBe('/api/meetings/meeting-id/identify-participants');
    expect(calls[1][1].method).toBe('POST');
  });
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
  it('sends literal-name cards, optional links and opaque versions through the card endpoints', async () => {
    globalThis.fetch = mockFetch({ relationship_cards: [] });
    await api.profiles.createRelationshipCard('profile/id', { expected_revision: 3, name: 'Casey', profile_id: null, notes: '' });
    await api.profiles.createRelationshipCard('person', { expected_revision: 4, name: 'Jordan', profile_id: 'target', target_revision: 2, assignment_version: 'assignment-version' });
    await api.profiles.updateRelationshipCard('person', 'profile:target/id', { version: 'captured-version', notes: '' });
    await api.profiles.updateRelationshipCard('person', 'name:casey', { version: 'current-version', allow_agent_notes: true });
    await api.profiles.removeRelationshipCard('person', 'name:casey', 'delete-version');
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.map(call => call[0])).toEqual(['/api/profiles/profile%2Fid/relationship-cards', '/api/profiles/person/relationship-cards', '/api/profiles/person/relationship-cards/profile%3Atarget%2Fid', '/api/profiles/person/relationship-cards/name%3Acasey', '/api/profiles/person/relationship-cards/name%3Acasey']);
    expect(JSON.parse(calls[0][1].body)).toEqual({ expected_revision: 3, name: 'Casey', profile_id: null, notes: '' });
    expect(JSON.parse(calls[1][1].body)).not.toHaveProperty('notes');
    expect(JSON.parse(calls[2][1].body)).toEqual({ version: 'captured-version', notes: '' });
    expect(JSON.parse(calls[3][1].body)).toEqual({ version: 'current-version', allow_agent_notes: true });
    expect(calls[4][1].method).toBe('DELETE');
    expect(JSON.parse(calls[4][1].body)).toEqual({ version: 'delete-version' });
  });
  it('serializes topic filters, label preview and revision-checked label saves separately', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    await api.meetings.list({ labels: ['security', 'paralign'] });
    await api.meetings.suggestLabels('meeting-id', 3);
    await api.meetings.updateLabels('meeting-id', { expected_revision: 3, expected_meeting_revision: 8, labels: ['security'] });
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(new URL(calls[0][0]).searchParams.getAll('labels')).toEqual(['security', 'paralign']);
    expect(calls[1][0]).toBe('/api/meetings/meeting-id/labels/suggest');
    expect(JSON.parse(calls[1][1].body)).toEqual({ expected_revision: 3 });
    expect(calls[2][1].method).toBe('PATCH');
    expect(JSON.parse(calls[2][1].body)).toEqual({ expected_revision: 3, expected_meeting_revision: 8, labels: ['security'] });
  });

  it('uses exact profile history IDs and sends rebuilds through the configured-job endpoint', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    await api.profiles.history('profile-id', { limit: 25, offset: 50 });
    await api.profiles.historyOne('profile-id', 7);
    await api.profiles.rebuild('profile-id', 4);
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(new URL(calls[0][0]).pathname).toBe('/api/profiles/profile-id/history');
    expect(new URL(calls[0][0]).searchParams.get('offset')).toBe('50');
    expect(new URL(calls[1][0]).pathname).toBe('/api/profiles/profile-id/history/7');
    expect(calls[2][0]).toBe('/api/profiles/profile-id/rebuild');
    expect(JSON.parse(calls[2][1].body)).toEqual({ expected_revision: 4 });
  });

  it('meetings.list includes search, filters and paging without imposing a connection', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    await api.meetings.list({ q: 'release plan', limit: 25, offset: 50 });
    const url = new URL((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]);
    expect(url.pathname).toBe('/api/meetings');
    expect(Object.fromEntries(url.searchParams)).toEqual({ q: 'release plan', limit: '25', offset: '50' });

    await api.meetings.list({ source: 'team', project: 'agent-smith', after: '2026-10-01T00:00:00Z', before: '2026-11-01T00:00:00Z' });
    const filtered = new URL((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[1][0]);
    expect(filtered.searchParams.get('source')).toBe('team');
    expect(filtered.searchParams.get('project')).toBe('agent-smith');
    expect(filtered.searchParams.get('after')).toBe('2026-10-01T00:00:00Z');
    expect(filtered.searchParams.get('before')).toBe('2026-11-01T00:00:00Z');
  });

  it('meetings.get reads the selected stable summary ID', async () => {
    globalThis.fetch = mockFetch({ id: 'summary-id' });
    await api.meetings.get('summary-id');
    const url = new URL((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]);
    expect(url.pathname).toBe('/api/meetings/summary-id');
  });

  it('meetings.transcript pages segments and deletes through the same summary route', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    await api.meetings.transcript('summary-id', { limit: 100, offset: 100 });
    const url = new URL((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]);
    expect(url.pathname).toBe('/api/meetings/summary-id/transcript');
    expect(Object.fromEntries(url.searchParams)).toEqual({ limit: '100', offset: '100' });

    await api.meetings.deleteTranscript('summary-id');
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[1]).toEqual([
      '/api/meetings/summary-id/transcript', { method: 'DELETE' },
    ]);
    await api.meetings.retryTranscript('summary-id');
    const [retryUrl, retryOptions] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[2];
    expect(retryUrl).toBe('/api/meetings/summary-id/transcript/retry');
    expect(retryOptions.method).toBe('POST');
    expect(retryOptions.body).toBe('{}');
  });

  it('reads generated memories and queues a failed generation retry', async () => {
    globalThis.fetch = mockFetch({ status: 'pending', items: [] });
    await api.meetings.memories('summary-id');
    const url = new URL((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]);
    expect(url.pathname).toBe('/api/meetings/summary-id/memories');

    await api.meetings.retryMemories('summary-id');
    const [retryUrl, options] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[1];
    expect(retryUrl).toBe('/api/meetings/summary-id/memories/retry');
    expect(options.method).toBe('POST');
    expect(options.body).toBe('{}');
  });

  it('reads profiles and submits revision-checked corrections and deletion', async () => {
    globalThis.fetch = mockFetch({});
    await api.meetings.profiles('meeting-id');
    await api.profiles.get('profile-id');
    await api.meetings.retryProfiles('meeting-id');
    const body = { expected_revision: 3, action: 'correct' as const, content: 'Corrected claim', reason: 'Source correction' };
    await api.profiles.correctClaim('profile-id', 'claim-id', body);
    await api.profiles.remove('profile-id', 4);
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(new URL(calls[0][0]).pathname).toBe('/api/meetings/meeting-id/profiles');
    expect(new URL(calls[1][0]).pathname).toBe('/api/profiles/profile-id');
    expect(calls[2][0]).toBe('/api/meetings/meeting-id/profiles/retry');
    expect(calls[3][0]).toBe('/api/profiles/profile-id/claims/claim-id?include_evidence=false');
    expect(JSON.parse(calls[3][1].body)).toEqual(body);
    expect(calls[4][0]).toBe('/api/profiles/profile-id');
    expect(calls[4][1].method).toBe('DELETE');
    expect(JSON.parse(calls[4][1].body)).toEqual({ expected_revision: 4 });
  });

  it('lists all profiles with server-side search and paging', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    await api.profiles.list({ q: 'Alex @example.test', limit: 25, offset: 50 });
    const url = new URL((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]);
    expect(url.pathname).toBe('/api/profiles');
    expect(Object.fromEntries(url.searchParams)).toEqual({ q: 'Alex @example.test', limit: '25', offset: '50' });

    await api.profiles.list();
    const unfiltered = new URL((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[1][0]);
    expect(unfiltered.search).toBe('');
  });

  it('creates profiles with optional email and patches a name with the captured revision', async () => {
    globalThis.fetch = mockFetch({ id: 'profile-id', identity_scope: 'manual' });
    await api.profiles.create({ display_name: 'Jordan Rivera' });
    await api.profiles.create({ display_name: 'Jordan Rivera', email: 'jordan@example.test' });
    await api.profiles.update('profile-id', { expected_revision: 1, display_name: 'Jordan Rivera updated' });
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls[0][0]).toBe('/api/profiles?include_evidence=false');
    expect(calls[0][1].method).toBe('POST');
    expect(JSON.parse(calls[0][1].body)).toEqual({ display_name: 'Jordan Rivera' });
    expect(JSON.parse(calls[1][1].body)).toEqual({ display_name: 'Jordan Rivera', email: 'jordan@example.test' });
    expect(calls[2][1].method).toBe('PATCH');
    expect(JSON.parse(calls[2][1].body)).toEqual({ expected_revision: 1, display_name: 'Jordan Rivera updated' });
  });

  it('serializes meeting-only filtering for both list and semantic search', async () => {
    globalThis.fetch = mockFetch({ items: [], total: 0 });
    await api.memory.list({ meeting_only: true, tags: ['decision'], offset: 10 });
    await api.memory.search('release', { meeting_only: true, repo: 'project', sort: 'relevance' });
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(Object.fromEntries(new URL(calls[0][0]).searchParams)).toEqual({ meeting_only: 'true', tags: 'decision', offset: '10' });
    expect(Object.fromEntries(new URL(calls[1][0]).searchParams)).toEqual({ q: 'release', meeting_only: 'true', repo: 'project', sort: 'relevance' });
  });

  it('keeps relationship and vocabulary revisions distinct in write requests', async () => {
    globalThis.fetch = mockFetch({});
    await api.profiles.createRelationship('person', { target_id: 'target', target_revision: 5, expected_revision: 3, label: 'reports to', notes: '' });
    await api.profiles.updateRelationship('person', 'edge', { expected_revision: 2, notes: 'Updated context' });
    await api.profiles.removeRelationship('person', 'edge', 4);
    await api.meetings.vocabulary.create({ term: 'custom phrase', definition: 'Known meaning' });
    await api.meetings.vocabulary.update('term', { expected_revision: 8, definition: '' });
    await api.meetings.vocabulary.remove('term', 9);
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.map(call => call[0])).toEqual(['/api/profiles/person/relationships?include_evidence=false', '/api/profiles/person/relationships/edge?include_evidence=false', '/api/profiles/person/relationships/edge', '/api/meetings/vocabulary', '/api/meetings/vocabulary/term', '/api/meetings/vocabulary/term']);
    expect(JSON.parse(calls[0][1].body)).toEqual({ target_id: 'target', target_revision: 5, expected_revision: 3, label: 'reports to', notes: '' });
    expect(JSON.parse(calls[2][1].body)).toEqual({ expected_revision: 4 });
    expect(JSON.parse(calls[4][1].body)).toEqual({ expected_revision: 8, definition: '' });
    expect(calls[5][1].method).toBe('DELETE');
    expect(JSON.parse(calls[5][1].body)).toEqual({ expected_revision: 9 });
  });

  it('serializes profile tags, false star filters, sorting and revision-checked identity actions', async () => {
    globalThis.fetch = mockFetch({});
    await api.profiles.list({ tags: ['team', 'priority'], starred: false, sort: 'name_desc' });
    const url = new URL((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]);
    expect(url.searchParams.getAll('tags')).toEqual(['team', 'priority']);
    expect(url.searchParams.get('starred')).toBe('false');
    expect(url.searchParams.get('sort')).toBe('name_desc');
    await api.profiles.update('source', { expected_revision: 1, tags: ['team'], starred: true });
    await api.profiles.merge('source', { expected_revision: 2, target_id: 'target', target_revision: 3 });
    await api.profiles.linkEmail('target', { expected_revision: 4, email: 'known@example.test' });
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls[1][0]).toBe('/api/profiles/source?include_evidence=false');
    expect(calls[1][1].method).toBe('PATCH');
    expect(JSON.parse(calls[1][1].body)).toEqual({ expected_revision: 1, tags: ['team'], starred: true });
    expect(calls[2][0]).toBe('/api/profiles/source/merge?include_evidence=false');
    expect(JSON.parse(calls[2][1].body)).toEqual({ expected_revision: 2, target_id: 'target', target_revision: 3 });
    expect(calls[3][0]).toBe('/api/profiles/target/aliases?include_evidence=false');
    expect(JSON.parse(calls[3][1].body)).toEqual({ expected_revision: 4, email: 'known@example.test' });
  });

  it('reads and updates manual meeting participants and queues explicit processing', async () => {
    globalThis.fetch = mockFetch({});
    await api.meetings.participants('meeting-id');
    await api.meetings.updateParticipants('meeting-id', { expected_revision: 0, participants: [{ name: 'Alex', email: 'known@example.test', speaker_key: 'speaker-1' }] });
    await api.meetings.process('meeting-id');
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(new URL(calls[0][0]).pathname).toBe('/api/meetings/meeting-id/participants');
    expect(calls[1][0]).toBe('/api/meetings/meeting-id/participants');
    expect(calls[1][1].method).toBe('PUT');
    expect(JSON.parse(calls[1][1].body)).toEqual({ expected_revision: 0, participants: [{ name: 'Alex', email: 'known@example.test', speaker_key: 'speaker-1' }] });
    expect(calls[2][0]).toBe('/api/meetings/meeting-id/process');
    expect(calls[2][1].method).toBe('POST');
  });

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
