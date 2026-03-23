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
