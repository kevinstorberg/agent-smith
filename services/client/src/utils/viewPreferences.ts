import { ALL_AGENTS, AUDIT_SORT_OPTIONS, AUDIT_STATUSES, EVAL_SUITE_SORT_OPTIONS, HARNESS_SORT_OPTIONS, PAGE_LIMITS, PROPOSAL_SORT_OPTIONS, PROPOSAL_STATUSES } from '../constants';
import type { PageLimit } from '../constants';

export const VIEW_COOKIE_NAME = 'agent-smith.ui.v1';
export const MAX_COOKIE_BYTES = 3000;
export const MAX_VIEW_ENTRIES = 12;
export const COOKIE_MAX_AGE = 30 * 24 * 60 * 60;
export const JOB_SORT_OPTIONS = [
  { value: 'updated', label: 'Recently updated' }, { value: 'newest', label: 'Newest first' }, { value: 'name', label: 'Name' },
] as const;
export const PLAN_SORT_OPTIONS = [
  { value: 'updated', label: 'Recently updated' }, { value: 'newest', label: 'Newest first' }, { value: 'title', label: 'Title A–Z' },
] as const;
export const PLAN_STATUSES = ['all', 'draft', 'final'] as const;
export const SCHEDULING_OPTIONS = [
  { value: '', label: 'All scheduling states' }, { value: 'true', label: 'Automatic runs enabled' }, { value: 'false', label: 'Automatic runs paused' },
] as const;

type HarnessViewKey = 'harness.rule' | 'harness.skill' | 'harness.tool' | 'harness.hook' | 'harness.agent';
interface HarnessViewSettings { name: string; project: string; sort: typeof HARNESS_SORT_OPTIONS[number]['value']; limit: PageLimit; offset: number }
export interface ViewSettings extends Record<HarnessViewKey, HarnessViewSettings> {
  jobs: { q: string; schedule_enabled: typeof SCHEDULING_OPTIONS[number]['value']; sort: typeof JOB_SORT_OPTIONS[number]['value']; limit: PageLimit; offset: number };
  plans: { q: string; project: string; status: typeof PLAN_STATUSES[number]; sort: typeof PLAN_SORT_OPTIONS[number]['value']; limit: PageLimit; offset: number };
  audit: { q: string; project: string; agent: '' | typeof ALL_AGENTS[number]; status: '' | typeof AUDIT_STATUSES[number]; sort: typeof AUDIT_SORT_OPTIONS[number]['value']; limit: PageLimit; offset: number };
  proposals: { q: string; status: '' | typeof PROPOSAL_STATUSES[number]; sort: typeof PROPOSAL_SORT_OPTIONS[number]['value']; limit: PageLimit; offset: number };
  evalSuites: { q: string; enabled: typeof SCHEDULING_OPTIONS[number]['value']; sort: typeof EVAL_SUITE_SORT_OPTIONS[number]['value']; limit: PageLimit; offset: number };
}
export type ViewKey = keyof ViewSettings;
interface Field<T> { parse: (value: unknown) => T | undefined }
interface ViewSpec<T> { pathname: string; defaults: T; fields: { [K in keyof T]: Field<T[K]> } }

const text: Field<string> = { parse: value => typeof value === 'string' && value.length <= 1000 && !/[\r\n\0]/.test(value) ? value : undefined };
function choice<const T extends string>(values: readonly T[]): Field<T> {
  return { parse: value => values.find(candidate => candidate === value) };
}
const pageLimit: Field<PageLimit> = { parse: value => PAGE_LIMITS.find(limit => limit === numeric(value)) };
const pageOffset: Field<number> = { parse: value => {
  const number = numeric(value);
  return number !== undefined && Number.isSafeInteger(number) && number >= 0 ? number : undefined;
} };

function numeric(value: unknown): number | undefined {
  if (typeof value === 'number') return value;
  return typeof value === 'string' && /^(0|[1-9]\d*)$/.test(value) ? Number(value) : undefined;
}

function harnessSpec(pathname: string): ViewSpec<HarnessViewSettings> {
  return { pathname, defaults: { name: '', project: '', sort: 'manual', limit: 10, offset: 0 },
    fields: { name: text, project: text, sort: choice(HARNESS_SORT_OPTIONS.map(option => option.value)), limit: pageLimit, offset: pageOffset } };
}

const SPECS: { [K in ViewKey]: ViewSpec<ViewSettings[K]> } = {
  'harness.rule': harnessSpec('/harness/rules'),
  'harness.skill': harnessSpec('/harness/skills'),
  'harness.tool': harnessSpec('/harness/tools'),
  'harness.hook': harnessSpec('/harness/hooks'),
  'harness.agent': harnessSpec('/harness/agents'),
  jobs: {
    pathname: '/jobs', defaults: { q: '', schedule_enabled: '', sort: 'updated', limit: 10, offset: 0 },
    fields: { q: text, schedule_enabled: choice(SCHEDULING_OPTIONS.map(option => option.value)), sort: choice(JOB_SORT_OPTIONS.map(option => option.value)), limit: pageLimit, offset: pageOffset },
  },
  plans: {
    pathname: '/plans', defaults: { q: '', project: '', status: 'all', sort: 'updated', limit: 10, offset: 0 },
    fields: { q: text, project: text, status: choice(PLAN_STATUSES), sort: choice(PLAN_SORT_OPTIONS.map(option => option.value)), limit: pageLimit, offset: pageOffset },
  },
  audit: {
    pathname: '/audit', defaults: { q: '', project: '', agent: '', status: '', sort: 'newest', limit: 10, offset: 0 },
    fields: { q: text, project: text, agent: choice(['', ...ALL_AGENTS]), status: choice(['', ...AUDIT_STATUSES]), sort: choice(AUDIT_SORT_OPTIONS.map(option => option.value)), limit: pageLimit, offset: pageOffset },
  },
  proposals: {
    pathname: '/proposals', defaults: { q: '', status: 'pending', sort: 'newest', limit: 10, offset: 0 },
    fields: { q: text, status: choice(['', ...PROPOSAL_STATUSES]), sort: choice(PROPOSAL_SORT_OPTIONS.map(option => option.value)), limit: pageLimit, offset: pageOffset },
  },
  evalSuites: {
    pathname: '/eval-configs', defaults: { q: '', enabled: '', sort: 'name', limit: 10, offset: 0 },
    fields: { q: text, enabled: choice(SCHEDULING_OPTIONS.map(option => option.value)), sort: choice(EVAL_SUITE_SORT_OPTIONS.map(option => option.value)), limit: pageLimit, offset: pageOffset },
  },
};

export function harnessViewKey(type: string): HarnessViewKey {
  const key = `harness.${type}`;
  if (!isViewKey(key) || !key.startsWith('harness.')) throw new Error(`Unsupported Harness preference type: ${type}`);
  return key as HarnessViewKey;
}

function specFor<K extends ViewKey>(key: K): ViewSpec<ViewSettings[K]> {
  return SPECS[key];
}

export function viewPath(key: ViewKey): string { return SPECS[key].pathname; }
export function defaultView<K extends ViewKey>(key: K): ViewSettings[K] { return { ...specFor(key).defaults }; }
export function viewFields<K extends ViewKey>(key: K): (keyof ViewSettings[K])[] {
  return Object.keys(specFor(key).fields) as (keyof ViewSettings[K])[];
}
export function parseViewField<K extends ViewKey, F extends keyof ViewSettings[K]>(key: K, field: F, value: unknown): ViewSettings[K][F] {
  const spec = specFor(key);
  return spec.fields[field].parse(value) ?? spec.defaults[field];
}

function object(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function validScope(scope: unknown): scope is string | undefined {
  return scope === undefined || typeof scope === 'string' && (/^[1-9]\d{0,14}$/.test(scope) || /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(scope));
}
function isViewKey(key: unknown): key is ViewKey { return typeof key === 'string' && Object.hasOwn(SPECS, key); }

function normalizeView<K extends ViewKey>(key: K, values: Record<string, unknown>): ViewSettings[K] {
  const result = defaultView(key);
  for (const field of viewFields(key)) result[field] = parseViewField(key, field, values[String(field)]);
  result.offset = Math.floor(result.offset / result.limit) * result.limit;
  return result;
}

function storedValues<K extends ViewKey>(key: K, values: unknown): Record<string, string | number> | null {
  if (!object(values)) return null;
  const spec = specFor(key);
  const fields = viewFields(key);
  if (Object.keys(values).some(field => !fields.some(known => known === field))) return null;
  for (const field of fields) {
    if (Object.hasOwn(values, field) && spec.fields[field].parse(values[String(field)]) === undefined) return null;
  }
  const normalized = normalizeView(key, values);
  const compact: Record<string, string | number> = {};
  for (const field of fields) {
    const value = normalized[field];
    if (value !== spec.defaults[field] && (typeof value === 'string' || typeof value === 'number')) compact[String(field)] = value;
  }
  return compact;
}

export interface ViewEntry { key: ViewKey; scope?: string; values: Record<string, string | number> }

export function readViewCookie(header: string): ViewEntry[] {
  const pair = header.split(';').map(part => part.trim()).find(part => part.startsWith(`${VIEW_COOKIE_NAME}=`));
  if (!pair) return [];
  const raw = pair.slice(VIEW_COOKIE_NAME.length + 1);
  if (raw.length > MAX_COOKIE_BYTES) return [];
  try {
    const envelope: unknown = JSON.parse(decodeURIComponent(raw));
    if (!object(envelope) || envelope.v !== 1 || !Array.isArray(envelope.views) || Object.keys(envelope).some(key => key !== 'v' && key !== 'views')) return [];
    const entries: ViewEntry[] = [];
    for (const entry of envelope.views) {
      if (!object(entry) || !isViewKey(entry.key) || !validScope(entry.scope) || Object.keys(entry).some(key => !['key', 'scope', 'values'].includes(key))) continue;
      const values = storedValues(entry.key, entry.values);
      if (!values || !Object.keys(values).length || entries.some(saved => saved.key === entry.key && saved.scope === entry.scope)) continue;
      entries.push({ key: entry.key, ...(entry.scope === undefined ? {} : { scope: entry.scope }), values });
      if (entries.length === MAX_VIEW_ENTRIES) break;
    }
    return entries;
  } catch { return []; }
}

export function resolveView<K extends ViewKey>(key: K, cookie: string, params: URLSearchParams, scope?: string): ViewSettings[K] {
  if (!validScope(scope)) throw new Error('View preference scope must be a positive ID or UUID');
  const saved = readViewCookie(cookie).find(entry => entry.key === key && entry.scope === scope);
  const values: Record<string, unknown> = { ...saved?.values };
  let criteriaPresent = false;
  for (const field of viewFields(key)) {
    if (!params.has(String(field))) continue;
    values[String(field)] = parseViewField(key, field, params.get(String(field)));
    if (field !== 'offset') criteriaPresent = true;
  }
  if (criteriaPresent && !params.has('offset')) values.offset = 0;
  return normalizeView(key, values);
}

function assignment(entries: ViewEntry[], secure: boolean): string {
  return `${VIEW_COOKIE_NAME}=${encodeURIComponent(JSON.stringify({ v: 1, views: entries }))}; Path=/; SameSite=Lax; Max-Age=${COOKIE_MAX_AGE}${secure ? '; Secure' : ''}`;
}
export function cookieBytes(value: string): number { return new TextEncoder().encode(value).byteLength; }

export function mergeViewCookie<K extends ViewKey>(header: string, key: K, values: ViewSettings[K], { scope, secure = false }: { scope?: string; secure?: boolean } = {}): string {
  if (!validScope(scope)) throw new Error('View preference scope must be a positive ID or UUID');
  let entries = readViewCookie(header).filter(entry => entry.key !== key || entry.scope !== scope);
  const compact = storedValues(key, values);
  if (compact && Object.keys(compact).length) {
    const current = { key, ...(scope === undefined ? {} : { scope }), values: compact };
    if (cookieBytes(assignment([current], secure)) <= MAX_COOKIE_BYTES) entries.unshift(current);
  }
  entries = entries.slice(0, MAX_VIEW_ENTRIES);
  while (cookieBytes(assignment(entries, secure)) > MAX_COOKIE_BYTES) entries.pop();
  return assignment(entries, secure);
}
