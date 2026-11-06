import {
  ACTION_ITEM_SORT_OPTIONS,
  ACTION_ITEM_STATUSES,
  CHAT_SORT_OPTIONS,
  CHAT_STATUSES,
  PROFILE_SORT_OPTIONS,
  RESULT_SORT_OPTIONS,
  actionItemSortOptions,
  defaultActionItemSort,
  ALL_AGENTS,
  AUDIT_SORT_OPTIONS,
  AUDIT_STATUSES,
  EVAL_SUITE_SORT_OPTIONS,
  HARNESS_SORT_OPTIONS,
  harnessSortOptions,
  MEMORY_LIST_SORT_OPTIONS,
  MEMORY_SEARCH_SORT_OPTIONS,
  MEETING_SORT_OPTIONS,
  PAGE_LIMITS,
  PROPOSAL_SORT_OPTIONS,
  PROPOSAL_STATUSES,
  VOCABULARY_DEFINITIONS,
  VOCABULARY_SORT_OPTIONS,
  TYPE_PATHS,
} from '../constants';
import type { PageLimit } from '../constants';
import { MAX_DUE_WINDOW_HOURS } from './actionItemDeadlines';
import { columnSortOptions } from './tableSorting';

export const VIEW_COOKIE_NAME = 'agent-smith.ui.v1';
export const MAX_COOKIE_BYTES = 3000;
export const MAX_VIEW_ENTRIES = 12;
export const COOKIE_MAX_AGE = 30 * 24 * 60 * 60;
export const JOB_SORT_COLUMNS = {
  name: { ascending: 'name', descending: 'name_desc' },
  updated: {
    ascending: 'updated_asc',
    descending: 'updated',
    defaultDirection: 'descending',
  },
} as const;
export const JOB_SORT_OPTIONS = [
  ...columnSortOptions(JOB_SORT_COLUMNS),
  { value: 'newest', label: 'Newest first' },
] as const;
export const PLAN_SORT_COLUMNS = {
  title: { ascending: 'title', descending: 'title_desc' },
  status: { ascending: 'status_asc', descending: 'status_desc' },
  project: { ascending: 'project_asc', descending: 'project_desc' },
  updated: {
    ascending: 'updated_asc',
    descending: 'updated',
    defaultDirection: 'descending',
  },
} as const;
export const PLAN_SORT_OPTIONS = [
  ...columnSortOptions(PLAN_SORT_COLUMNS),
  { value: 'newest', label: 'Newest first' },
] as const;
export const PLAN_STATUSES = ['all', 'draft', 'final'] as const;
export const PROJECT_SORT_COLUMNS = {
  name: { ascending: 'name_asc', descending: 'name_desc' },
  description: { ascending: 'description_asc', descending: 'description_desc' },
  updated: {
    ascending: 'updated_asc',
    descending: 'updated_desc',
    defaultDirection: 'descending',
  },
} as const;
const PROJECT_SORT_OPTIONS = columnSortOptions(PROJECT_SORT_COLUMNS);
export const SCHEDULING_OPTIONS = [
  { value: '', label: 'All states' },
  { value: 'true', label: 'Enabled' },
  { value: 'false', label: 'Paused' },
] as const;

type HarnessViewKey =
  | 'harness.rule'
  | 'harness.skill'
  | 'harness.tool'
  | 'harness.hook'
  | 'harness.agent';
interface HarnessViewSettings {
  name: string;
  project: string;
  sort: (typeof HARNESS_SORT_OPTIONS)[number]['value'];
  limit: PageLimit;
  offset: number;
}
export interface ViewSettings extends Record<
  HarnessViewKey,
  HarnessViewSettings
> {
  actionItems: {
    q: string;
    project: string;
    unassigned: boolean;
    due_within_hours: number | null;
    tags: string;
    status: (typeof ACTION_ITEM_STATUSES)[number][0];
    sort: (typeof ACTION_ITEM_SORT_OPTIONS)[number]['value'];
    limit: PageLimit;
    offset: number;
  };
  profiles: {
    q: string;
    tags: string;
    starred: boolean;
    sort: (typeof PROFILE_SORT_OPTIONS)[number]['value'];
    limit: PageLimit;
    offset: number;
  };
  chat: {
    q: string;
    status: (typeof CHAT_STATUSES)[number]['value'];
    sort: (typeof CHAT_SORT_OPTIONS)[number]['value'];
    limit: PageLimit;
    offset: number;
  };
  results: {
    q: string;
    category: string;
    subcategory: string;
    scenario: string;
    model: string;
    sort: (typeof RESULT_SORT_OPTIONS)[number]['value'];
    limit: PageLimit;
    offset: number;
  };
  jobs: {
    q: string;
    schedule_enabled: (typeof SCHEDULING_OPTIONS)[number]['value'];
    sort: (typeof JOB_SORT_OPTIONS)[number]['value'];
    limit: PageLimit;
    offset: number;
  };
  plans: {
    q: string;
    project: string;
    status: (typeof PLAN_STATUSES)[number];
    sort: (typeof PLAN_SORT_OPTIONS)[number]['value'];
    limit: PageLimit;
    offset: number;
  };
  projects: {
    q: string;
    sort: (typeof PROJECT_SORT_OPTIONS)[number]['value'];
    limit: PageLimit;
    offset: number;
  };
  audit: {
    q: string;
    project: string;
    agent: '' | (typeof ALL_AGENTS)[number];
    status: '' | (typeof AUDIT_STATUSES)[number];
    sort: (typeof AUDIT_SORT_OPTIONS)[number]['value'];
    limit: PageLimit;
    offset: number;
  };
  proposals: {
    q: string;
    status: '' | (typeof PROPOSAL_STATUSES)[number];
    sort: (typeof PROPOSAL_SORT_OPTIONS)[number]['value'];
    limit: PageLimit;
    offset: number;
  };
  evalSuites: {
    q: string;
    enabled: (typeof SCHEDULING_OPTIONS)[number]['value'];
    sort: (typeof EVAL_SUITE_SORT_OPTIONS)[number]['value'];
    limit: PageLimit;
    offset: number;
  };
  memory: {
    q: string;
    repo: string;
    tags: string;
    meeting_only: boolean;
    listSort: (typeof MEMORY_LIST_SORT_OPTIONS)[number]['value'];
    searchSort: (typeof MEMORY_SEARCH_SORT_OPTIONS)[number]['value'];
    limit: PageLimit;
    offset: number;
  };
  meetings: {
    q: string;
    labels: string;
    sort: (typeof MEETING_SORT_OPTIONS)[number]['value'];
    limit: PageLimit;
    offset: number;
  };
  vocabulary: {
    q: string;
    definition: (typeof VOCABULARY_DEFINITIONS)[number]['value'];
    sort: (typeof VOCABULARY_SORT_OPTIONS)[number]['value'];
    limit: PageLimit;
    offset: number;
  };
}
export type ViewKey = keyof ViewSettings;
interface Field<T> {
  parse: (value: unknown) => T | undefined;
}
interface ViewSpec<T> {
  pathname: string;
  defaults: T;
  fields: { [K in keyof T]: Field<T[K]> };
  normalize?: (values: T) => T;
}

const text: Field<string> = {
  parse: (value) =>
    typeof value === 'string' && value.length <= 1000 && !/[\r\n\0]/.test(value)
      ? value
      : undefined,
};
const boolean: Field<boolean> = {
  parse: (value) =>
    typeof value === 'boolean'
      ? value
      : value === 'true'
        ? true
        : value === 'false' || value === ''
          ? false
          : undefined,
};
const projectName: Field<string> = {
  parse: (value) =>
    typeof value === 'string' &&
    [...value].length <= 200 &&
    !value.includes('\0')
      ? value
      : undefined,
};
const dueWindow: Field<number | null> = {
  parse: (value) => {
    if (value === null || value === '') return null;
    const hours = numeric(value);
    return hours !== undefined &&
      Number.isSafeInteger(hours) &&
      hours >= 1 &&
      hours <= MAX_DUE_WINDOW_HOURS
      ? hours
      : undefined;
  },
};
function choice<const T extends string>(values: readonly T[]): Field<T> {
  return { parse: (value) => values.find((candidate) => candidate === value) };
}
const pageLimit: Field<PageLimit> = {
  parse: (value) => PAGE_LIMITS.find((limit) => limit === numeric(value)),
};
const pageOffset: Field<number> = {
  parse: (value) => {
    const number = numeric(value);
    return number !== undefined && Number.isSafeInteger(number) && number >= 0
      ? number
      : undefined;
  },
};

function numeric(value: unknown): number | undefined {
  if (typeof value === 'number') return value;
  return typeof value === 'string' && /^(0|[1-9]\d*)$/.test(value)
    ? Number(value)
    : undefined;
}

function harnessSpec(type: string): ViewSpec<HarnessViewSettings> {
  const path = TYPE_PATHS[type];
  if (!path) throw new Error(`Unsupported Harness preference type: ${type}`);
  return {
    pathname: `/harness/${path}`,
    defaults: { name: '', project: '', sort: 'manual', limit: 10, offset: 0 },
    fields: {
      name: text,
      project: text,
      sort: choice(harnessSortOptions(type).map((option) => option.value)),
      limit: pageLimit,
      offset: pageOffset,
    },
  };
}

const SPECS: { [K in ViewKey]: ViewSpec<ViewSettings[K]> } = {
  projects: {
    pathname: '/projects',
    defaults: { q: '', sort: 'name_asc', limit: 10, offset: 0 },
    fields: {
      q: text,
      sort: choice(PROJECT_SORT_OPTIONS.map((option) => option.value)),
      limit: pageLimit,
      offset: pageOffset,
    },
  },
  'harness.rule': harnessSpec('rule'),
  'harness.skill': harnessSpec('skill'),
  'harness.tool': harnessSpec('tool'),
  'harness.hook': harnessSpec('hook'),
  'harness.agent': harnessSpec('agent'),
  actionItems: {
    pathname: '/action-items',
    defaults: {
      q: '',
      project: '',
      unassigned: false,
      due_within_hours: null,
      tags: '',
      status: 'open',
      sort: 'manual',
      limit: 10,
      offset: 0,
    },
    fields: {
      q: text,
      project: projectName,
      unassigned: boolean,
      due_within_hours: dueWindow,
      tags: text,
      status: choice(ACTION_ITEM_STATUSES.map((option) => option[0])),
      sort: choice(ACTION_ITEM_SORT_OPTIONS.map((option) => option.value)),
      limit: pageLimit,
      offset: pageOffset,
    },
    normalize: (values) => ({
      ...values,
      unassigned: !values.project && values.unassigned,
      sort: actionItemSortOptions(values.status).some(
        (option) => option.value === values.sort,
      )
        ? values.sort
        : defaultActionItemSort(values.status),
    }),
  },
  profiles: {
    pathname: '/profiles',
    defaults: {
      q: '',
      tags: '',
      starred: false,
      sort: 'starred_name_asc',
      limit: 10,
      offset: 0,
    },
    fields: {
      q: text,
      tags: text,
      starred: boolean,
      sort: choice(PROFILE_SORT_OPTIONS.map((option) => option.value)),
      limit: pageLimit,
      offset: pageOffset,
    },
  },
  chat: {
    pathname: '/chat',
    defaults: { q: '', status: 'all', sort: 'updated', limit: 10, offset: 0 },
    fields: {
      q: text,
      status: choice(CHAT_STATUSES.map((option) => option.value)),
      sort: choice(CHAT_SORT_OPTIONS.map((option) => option.value)),
      limit: pageLimit,
      offset: pageOffset,
    },
  },
  results: {
    pathname: '/evals',
    defaults: {
      q: '',
      category: '',
      subcategory: '',
      scenario: '',
      model: '',
      sort: 'newest',
      limit: 10,
      offset: 0,
    },
    fields: {
      q: text,
      category: text,
      subcategory: text,
      scenario: text,
      model: text,
      sort: choice(RESULT_SORT_OPTIONS.map((option) => option.value)),
      limit: pageLimit,
      offset: pageOffset,
    },
  },
  jobs: {
    pathname: '/jobs',
    defaults: {
      q: '',
      schedule_enabled: '',
      sort: 'updated',
      limit: 10,
      offset: 0,
    },
    fields: {
      q: text,
      schedule_enabled: choice(
        SCHEDULING_OPTIONS.map((option) => option.value),
      ),
      sort: choice(JOB_SORT_OPTIONS.map((option) => option.value)),
      limit: pageLimit,
      offset: pageOffset,
    },
  },
  plans: {
    pathname: '/plans',
    defaults: {
      q: '',
      project: '',
      status: 'all',
      sort: 'updated',
      limit: 10,
      offset: 0,
    },
    fields: {
      q: text,
      project: text,
      status: choice(PLAN_STATUSES),
      sort: choice(PLAN_SORT_OPTIONS.map((option) => option.value)),
      limit: pageLimit,
      offset: pageOffset,
    },
  },
  audit: {
    pathname: '/audit',
    defaults: {
      q: '',
      project: '',
      agent: '',
      status: '',
      sort: 'newest',
      limit: 10,
      offset: 0,
    },
    fields: {
      q: text,
      project: text,
      agent: choice(['', ...ALL_AGENTS]),
      status: choice(['', ...AUDIT_STATUSES]),
      sort: choice(AUDIT_SORT_OPTIONS.map((option) => option.value)),
      limit: pageLimit,
      offset: pageOffset,
    },
  },
  proposals: {
    pathname: '/proposals',
    defaults: {
      q: '',
      status: 'pending',
      sort: 'newest',
      limit: 10,
      offset: 0,
    },
    fields: {
      q: text,
      status: choice(['', ...PROPOSAL_STATUSES]),
      sort: choice(PROPOSAL_SORT_OPTIONS.map((option) => option.value)),
      limit: pageLimit,
      offset: pageOffset,
    },
  },
  evalSuites: {
    pathname: '/eval-configs',
    defaults: { q: '', enabled: '', sort: 'name', limit: 10, offset: 0 },
    fields: {
      q: text,
      enabled: choice(SCHEDULING_OPTIONS.map((option) => option.value)),
      sort: choice(EVAL_SUITE_SORT_OPTIONS.map((option) => option.value)),
      limit: pageLimit,
      offset: pageOffset,
    },
  },
  memory: {
    pathname: '/memory',
    defaults: {
      q: '',
      repo: '',
      tags: '',
      meeting_only: false,
      listSort: 'created_at_desc',
      searchSort: 'relevance',
      limit: 10,
      offset: 0,
    },
    fields: {
      q: text,
      repo: text,
      tags: text,
      meeting_only: boolean,
      listSort: choice(MEMORY_LIST_SORT_OPTIONS.map((option) => option.value)),
      searchSort: choice(
        MEMORY_SEARCH_SORT_OPTIONS.map((option) => option.value),
      ),
      limit: pageLimit,
      offset: pageOffset,
    },
  },
  meetings: {
    pathname: '/meetings',
    defaults: { q: '', labels: '', sort: 'newest', limit: 10, offset: 0 },
    fields: {
      q: text,
      labels: text,
      sort: choice(MEETING_SORT_OPTIONS.map((option) => option.value)),
      limit: pageLimit,
      offset: pageOffset,
    },
  },
  vocabulary: {
    pathname: '/meetings',
    defaults: { q: '', definition: 'all', sort: 'term', limit: 10, offset: 0 },
    fields: {
      q: text,
      definition: choice(VOCABULARY_DEFINITIONS.map((option) => option.value)),
      sort: choice(VOCABULARY_SORT_OPTIONS.map((option) => option.value)),
      limit: pageLimit,
      offset: pageOffset,
    },
  },
};

export function harnessViewKey(type: string): HarnessViewKey {
  const key = `harness.${type}`;
  if (!isViewKey(key) || !key.startsWith('harness.'))
    throw new Error(`Unsupported Harness preference type: ${type}`);
  return key as HarnessViewKey;
}

function specFor<K extends ViewKey>(key: K): ViewSpec<ViewSettings[K]> {
  return SPECS[key];
}

export function viewPath(key: ViewKey): string {
  return SPECS[key].pathname;
}
export function defaultView<K extends ViewKey>(key: K): ViewSettings[K] {
  return { ...specFor(key).defaults };
}
export function viewFields<K extends ViewKey>(
  key: K,
): (keyof ViewSettings[K])[] {
  return Object.keys(specFor(key).fields) as (keyof ViewSettings[K])[];
}
export function parseViewField<
  K extends ViewKey,
  F extends keyof ViewSettings[K],
>(key: K, field: F, value: unknown): ViewSettings[K][F] {
  const spec = specFor(key);
  return spec.fields[field].parse(value) ?? spec.defaults[field];
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function validScope(scope: unknown): scope is string | undefined {
  return (
    scope === undefined ||
    (typeof scope === 'string' &&
      (/^[1-9]\d{0,14}$/.test(scope) ||
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
          scope,
        )))
  );
}
function isViewKey(key: unknown): key is ViewKey {
  return typeof key === 'string' && Object.hasOwn(SPECS, key);
}

export function normalizeViewRelations<K extends ViewKey>(
  key: K,
  values: ViewSettings[K],
): ViewSettings[K] {
  return specFor(key).normalize?.(values) ?? values;
}

function normalizeView<K extends ViewKey>(
  key: K,
  values: Record<string, unknown>,
): ViewSettings[K] {
  const result = defaultView(key);
  for (const field of viewFields(key))
    result[field] = parseViewField(key, field, values[String(field)]);
  result.offset = Math.floor(result.offset / result.limit) * result.limit;
  return normalizeViewRelations(key, result);
}

function storedValues<K extends ViewKey>(
  key: K,
  values: unknown,
): Record<string, string | number | boolean> | null {
  if (!object(values)) return null;
  const spec = specFor(key);
  const fields = viewFields(key);
  if (
    Object.keys(values).some(
      (field) => !fields.some((known) => known === field),
    )
  )
    return null;
  for (const field of fields) {
    if (
      Object.hasOwn(values, field) &&
      spec.fields[field].parse(values[String(field)]) === undefined
    )
      return null;
  }
  const normalized = normalizeView(key, values);
  const compact: Record<string, string | number | boolean> = {};
  for (const field of fields) {
    const value = normalized[field];
    if (
      value !== spec.defaults[field] &&
      (typeof value === 'string' ||
        typeof value === 'number' ||
        typeof value === 'boolean')
    )
      compact[String(field)] = value;
  }
  return compact;
}

export interface ViewEntry {
  key: ViewKey;
  scope?: string;
  values: Record<string, string | number | boolean>;
}

export function readViewCookie(header: string): ViewEntry[] {
  const pair = header
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${VIEW_COOKIE_NAME}=`));
  if (!pair) return [];
  const raw = pair.slice(VIEW_COOKIE_NAME.length + 1);
  if (raw.length > MAX_COOKIE_BYTES) return [];
  try {
    const envelope: unknown = JSON.parse(decodeURIComponent(raw));
    if (
      !object(envelope) ||
      envelope.v !== 1 ||
      !Array.isArray(envelope.views) ||
      Object.keys(envelope).some((key) => key !== 'v' && key !== 'views')
    )
      return [];
    const entries: ViewEntry[] = [];
    for (const entry of envelope.views) {
      if (
        !object(entry) ||
        !isViewKey(entry.key) ||
        !validScope(entry.scope) ||
        Object.keys(entry).some(
          (key) => !['key', 'scope', 'values'].includes(key),
        )
      )
        continue;
      const values = storedValues(entry.key, entry.values);
      if (
        !values ||
        !Object.keys(values).length ||
        entries.some(
          (saved) => saved.key === entry.key && saved.scope === entry.scope,
        )
      )
        continue;
      entries.push({
        key: entry.key,
        ...(entry.scope === undefined ? {} : { scope: entry.scope }),
        values,
      });
      if (entries.length === MAX_VIEW_ENTRIES) break;
    }
    return entries;
  } catch {
    return [];
  }
}

export function resolveView<K extends ViewKey>(
  key: K,
  cookie: string,
  params: URLSearchParams,
  scope?: string,
): ViewSettings[K] {
  if (!validScope(scope))
    throw new Error('View preference scope must be a positive ID or UUID');
  const saved = readViewCookie(cookie).find(
    (entry) => entry.key === key && entry.scope === scope,
  );
  const values: Record<string, unknown> = { ...saved?.values };
  if (
    key === 'actionItems' &&
    (params.has('project') || params.has('unassigned'))
  ) {
    values.project = '';
    values.unassigned = false;
  }
  let criteriaPresent = false;
  for (const field of viewFields(key)) {
    if (!params.has(String(field))) continue;
    values[String(field)] = parseViewField(
      key,
      field,
      params.get(String(field)),
    );
    if (field !== 'offset') criteriaPresent = true;
  }
  if (criteriaPresent && !params.has('offset')) values.offset = 0;
  return normalizeView(key, values);
}

function assignment(entries: ViewEntry[], secure: boolean): string {
  return `${VIEW_COOKIE_NAME}=${encodeURIComponent(JSON.stringify({ v: 1, views: entries }))}; Path=/; SameSite=Lax; Max-Age=${COOKIE_MAX_AGE}${secure ? '; Secure' : ''}`;
}
export function cookieBytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

export function mergeViewCookie<K extends ViewKey>(
  header: string,
  key: K,
  values: ViewSettings[K],
  { scope, secure = false }: { scope?: string; secure?: boolean } = {},
): string {
  if (!validScope(scope))
    throw new Error('View preference scope must be a positive ID or UUID');
  let entries = readViewCookie(header).filter(
    (entry) => entry.key !== key || entry.scope !== scope,
  );
  const compact = storedValues(key, values);
  if (compact && Object.keys(compact).length) {
    const current = {
      key,
      ...(scope === undefined ? {} : { scope }),
      values: compact,
    };
    if (cookieBytes(assignment([current], secure)) <= MAX_COOKIE_BYTES)
      entries.unshift(current);
  }
  entries = entries.slice(0, MAX_VIEW_ENTRIES);
  while (cookieBytes(assignment(entries, secure)) > MAX_COOKIE_BYTES)
    entries.pop();
  return assignment(entries, secure);
}
