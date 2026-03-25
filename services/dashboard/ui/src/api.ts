const BASE = '/api';

async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, window.location.origin);
  url.pathname = BASE + path;
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v) url.searchParams.set(k, v);
    });
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function del(path: string): Promise<void> {
  const res = await fetch(BASE + path, { method: 'DELETE' });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
}

export interface HarnessItem {
  id: number;
  name: string;
  project: string | null;
  agents: string[];
  content: { body: string; metadata: Record<string, unknown> };
  sort_key: string;
  enabled: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Rule {
  name: string;
  content: string;
}

export interface Skill {
  name: string;
  content: string;
  files: string[];
}

export interface McpServer {
  name: string;
  config: Record<string, unknown>;
}

export interface MemoryItem {
  id: string;
  content: string;
  repo?: string;
  tags?: string[];
  created_at?: string;
  last_accessed_at?: string;
}

export interface EvalRun {
  id: number;
  timestamp: string;
  eval_type: string;
  scenario: string;
  test_model: string;
  judge_model: string;
  threshold: number;
  results: { rule: string; score: number; reason: string }[];
  created_at: string;
}

export interface ChartPoint {
  id: number;
  timestamp: string;
  scores: Record<string, number>;
}

export const api = {
  harness: {
    rules: () => get<Rule[]>('/harness/rules'),
    skills: () => get<Skill[]>('/harness/skills'),
    mcp: () => get<McpServer[]>('/harness/mcp'),
    items: {
      list: (type: string) => get<HarnessItem[]>(`/harness/items/${type}`),
      get: (type: string, id: number) => get<HarnessItem>(`/harness/items/${type}/${id}`),
      create: (type: string, body: unknown) => post<HarnessItem>(`/harness/items/${type}`, body),
      updateContent: (type: string, id: number, content: unknown) =>
        put<HarnessItem>(`/harness/items/${type}/${id}/content`, { content }),
      updateMetadata: (type: string, id: number, body: unknown) =>
        patch<HarnessItem>(`/harness/items/${type}/${id}`, body),
      history: (type: string, id: number) => get<HarnessItem[]>(`/harness/items/${type}/${id}/history`),
      remove: (type: string, id: number) => del(`/harness/items/${type}/${id}`),
    },
  },
  memory: {
    search: (q: string, repo = '', limit = '20') =>
      get<MemoryItem[]>('/memory/search', { q, repo, limit }),
    list: (repo = '', limit = '20') =>
      get<MemoryItem[]>('/memory/list', { repo, limit }),
  },
  evals: {
    list: (params?: Record<string, string>) =>
      get<EvalRun[]>('/evals', params),
    chart: (params?: Record<string, string>) =>
      get<ChartPoint[]>('/evals/chart', params),
    get: (id: number) => get<EvalRun>(`/evals/${id}`),
  },
};
