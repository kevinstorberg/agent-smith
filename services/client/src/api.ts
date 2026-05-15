const BASE = '/api';

async function parseError(res: Response): Promise<never> {
  const body = await res.json().catch(() => null);
  const detail = body?.detail;
  const message = typeof detail === 'string'
    ? detail
    : Array.isArray(detail)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ? detail.map((e: any) => `${e.loc?.slice(-1)[0] ?? 'field'}: ${e.msg}`).join('; ')
      : `${res.status} ${res.statusText}`;
  throw new Error(message);
}

async function get<T>(path: string, params?: Record<string, string | string[]>): Promise<T> {
  const url = new URL(path, window.location.origin);
  url.pathname = BASE + path;
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (Array.isArray(v)) {
        v.filter(Boolean).forEach(item => url.searchParams.append(k, item));
      } else if (v) {
        url.searchParams.set(k, v);
      }
    });
  }
  const res = await fetch(url.toString());
  if (!res.ok) await parseError(res);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

async function del<T = void>(path: string): Promise<T> {
  const res = await fetch(BASE + path, { method: 'DELETE' });
  if (!res.ok) await parseError(res);
  const text = await res.text();
  return text ? JSON.parse(text) : (undefined as T);
}

export interface Paginated<T> {
  items: T[];
  total: number;
}

export interface PaginationParams {
  limit?: number;
  offset?: number;
}

export interface HarnessConfig {
  id: number;
  device: string;
  repo: string;
  agents: string[];
  subagents: string[];
  enabled: boolean;
  exclude: boolean;
}

export interface HarnessItem {
  id: number;
  name: string;
  project: string | null;
  agents: string[];
  content?: { body: string; metadata: Record<string, unknown> };
  sort_key: number;
  enabled: boolean;
  clone_as_skill?: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  configs: HarnessConfig[];
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
  subcategory: string | null;
  scenario: string;
  test_model: string;
  judge_model: string;
  threshold: number;
  results?: { rule: string; score: number; reason: string }[];
  score_avg?: number;
  score_count?: number;
  eval_suite_id: number | null;
  created_at: string;
}

export interface EvalRunDetail extends EvalRun {
  prompt: string | null;
  output: string;
}

export interface Plan {
  id: number;
  title: string;
  body: string;
  project: string | null;
  created_at: string;
  updated_at: string;
}

export interface EvalSuite {
  id: number;
  name: string;
  eval_type: string;
  subcategory: string;
  judge_prompt: string;
  items: Record<string, unknown>;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  scenario_count?: number;
  scenarios?: EvalScenario[];
}

export interface EvalScenario {
  id: number;
  suite_id: number;
  name: string;
  prompt: string;
  enabled: boolean;
  sort_key: number;
  created_at: string;
  updated_at: string;
}

export interface ChartPoint {
  id: number;
  timestamp: string;
  scores: Record<string, number>;
}

export interface AverageChartPoint {
  id: number;
  timestamp: string;
  score: number;
}

function paginationToParams(p?: PaginationParams): Record<string, string> {
  const params: Record<string, string> = {};
  if (p?.limit !== undefined) params.limit = String(p.limit);
  if (p?.offset !== undefined) params.offset = String(p.offset);
  return params;
}

export const api = {
  harness: {
    rules: () => get<Rule[]>('/harness/rules'),
    skills: () => get<Skill[]>('/harness/skills'),
    mcp: () => get<McpServer[]>('/harness/mcp'),
    sync: () => post<{ success: boolean; stdout: string; stderr: string }>('/harness/sync', {}),
    unsync: () => post<{ success: boolean; removed: string[] }>('/harness/unsync', {}),
    items: {
      list: (type: string, params?: PaginationParams & { name?: string; project?: string }) => {
        const query = paginationToParams(params);
        if (params?.name) query.name = params.name;
        if (params?.project) query.project = params.project;
        return get<Paginated<HarnessItem>>(`/harness/items/${type}`, query);
      },
      get: (type: string, id: number) => get<HarnessItem>(`/harness/items/${type}/${id}`),
      create: (type: string, body: unknown) => post<HarnessItem>(`/harness/items/${type}`, body),
      updateContent: (type: string, id: number, content: unknown) =>
        put<HarnessItem>(`/harness/items/${type}/${id}/content`, { content }),
      updateMetadata: (type: string, id: number, body: unknown) =>
        patch<HarnessItem>(`/harness/items/${type}/${id}`, body),
      history: (type: string, id: number) => get<HarnessItem[]>(`/harness/items/${type}/${id}/history`),
      remove: (type: string, id: number) => del(`/harness/items/${type}/${id}`),
      configs: {
        add: (type: string, itemId: number, body: Partial<HarnessConfig>) =>
          post<{ id: number }>(`/harness/items/${type}/${itemId}/configs`, body),
        update: (type: string, itemId: number, configId: number, body: Partial<HarnessConfig>) =>
          patch<HarnessConfig[]>(`/harness/items/${type}/${itemId}/configs/${configId}`, body),
        remove: (type: string, itemId: number, configId: number) =>
          del(`/harness/items/${type}/${itemId}/configs/${configId}`),
      },
      reorder: (type: string, ids: number[]) => put<{ reordered: boolean }>(`/harness/items/${type}/reorder`, { ids }),
    },
  },
  memory: {
    search: (q: string, opts?: PaginationParams & { repo?: string; tags?: string[]; sort?: string }) =>
      get<Paginated<MemoryItem>>('/memory/search', {
        q,
        ...(opts?.repo ? { repo: opts.repo } : {}),
        ...(opts?.tags && opts.tags.length ? { tags: opts.tags } : {}),
        ...(opts?.sort ? { sort: opts.sort } : {}),
        ...paginationToParams(opts),
      }),
    list: (opts?: PaginationParams & { repo?: string; tags?: string[]; sort?: string }) =>
      get<Paginated<MemoryItem>>('/memory/list', {
        ...(opts?.repo ? { repo: opts.repo } : {}),
        ...(opts?.tags && opts.tags.length ? { tags: opts.tags } : {}),
        ...(opts?.sort ? { sort: opts.sort } : {}),
        ...paginationToParams(opts),
      }),
    get: (id: string) => get<MemoryItem>(`/memory/${id}`),
    update: (id: string, body: { content?: string; repo?: string; tags?: string[] }) =>
      put<MemoryItem>(`/memory/${id}`, body),
    remove: (id: string) => del<{ deleted: boolean }>(`/memory/${id}`),
  },
  evals: {
    list: (params?: Record<string, string>) =>
      get<Paginated<EvalRun>>('/evals', params),
    chart: (params?: Record<string, string>) =>
      get<ChartPoint[]>('/evals/chart', params),
    chartAverage: (params?: Record<string, string>) =>
      get<AverageChartPoint[]>('/evals/chart/average', params),
    categories: () => get<string[]>('/evals/categories'),
    subcategories: (params?: Record<string, string>) =>
      get<string[]>('/evals/subcategories', params),
    get: (id: number) => get<EvalRunDetail>(`/evals/${id}`),
    remove: (id: number) => del<{ deleted: number }>(`/evals/${id}`),
  },
  plans: {
    list: (pagination?: PaginationParams & { project?: string }) =>
      get<Paginated<Plan>>('/plans', {
        ...(pagination?.project ? { project: pagination.project } : {}),
        ...paginationToParams(pagination),
      }),
    search: (q: string) => get<Plan[]>('/plans/search', { q }),
    get: (id: number) => get<Plan>(`/plans/${id}`),
    create: (body: { title: string; body: string; project?: string | null }) =>
      post<Plan>('/plans', body),
    update: (id: number, body: { title?: string; body?: string; project?: string | null }) =>
      put<Plan>(`/plans/${id}`, body),
    remove: (id: number) => del(`/plans/${id}`),
  },
  evalConfigs: {
    suites: {
      list: (params?: Record<string, string>) =>
        get<Paginated<EvalSuite>>('/eval-configs/suites', params),
      get: (id: number) => get<EvalSuite>(`/eval-configs/suites/${id}`),
      create: (body: Partial<EvalSuite>) => post<EvalSuite>('/eval-configs/suites', body),
      update: (id: number, body: Partial<EvalSuite>) =>
        put<EvalSuite>(`/eval-configs/suites/${id}`, body),
      remove: (id: number) => del<{ deleted: number }>(`/eval-configs/suites/${id}`),
    },
    scenarios: {
      list: (suiteId: number, params?: Record<string, string>) =>
        get<EvalScenario[]>(`/eval-configs/suites/${suiteId}/scenarios`, params),
      get: (id: number) => get<EvalScenario>(`/eval-configs/scenarios/${id}`),
      create: (suiteId: number, body: { name: string; prompt: string; enabled?: boolean }) =>
        post<EvalScenario>(`/eval-configs/suites/${suiteId}/scenarios`, body),
      update: (id: number, body: Partial<EvalScenario>) =>
        put<EvalScenario>(`/eval-configs/scenarios/${id}`, body),
      remove: (id: number) => del<{ deleted: number }>(`/eval-configs/scenarios/${id}`),
    },
  },
};
