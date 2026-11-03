export const ALL_AGENTS = ['claude', 'codex', 'gemini'] as const;
export const POLL_INTERVAL_MS = 60_000;
export const PAGE_LIMITS = [10, 25, 50] as const;
export type PageLimit = typeof PAGE_LIMITS[number];
export const HARNESS_SORT_OPTIONS = [
  { value: 'manual', label: 'Manual order' }, { value: 'name', label: 'Name A–Z' },
  { value: 'newest', label: 'Newest first' }, { value: 'updated', label: 'Recently updated' },
] as const;
export const AUDIT_STATUSES = ['pending', 'success', 'error'] as const;
export const PROPOSAL_STATUSES = ['pending', 'approved', 'rejected'] as const;
export const AUDIT_SORT_OPTIONS = [
  { value: 'newest', label: 'Newest first' }, { value: 'oldest', label: 'Oldest first' }, { value: 'duration', label: 'Longest duration' },
] as const;
export const PROPOSAL_SORT_OPTIONS = [
  { value: 'newest', label: 'Newest first' }, { value: 'oldest', label: 'Oldest first' }, { value: 'title', label: 'Title' },
] as const;
export const EVAL_SUITE_SORT_OPTIONS = [
  { value: 'name', label: 'Name' }, { value: 'updated', label: 'Recently updated' }, { value: 'newest', label: 'Newest first' },
] as const;

export const TYPE_PATHS: Record<string, string> = {
  rule: 'rules',
  skill: 'skills',
  tool: 'tools',
  hook: 'hooks',
  agent: 'agents',
};

export const TYPE_LABELS: Record<string, string> = {
  rule: 'Rule',
  skill: 'Skill',
  tool: 'Tool',
  hook: 'Hook',
  agent: 'Agent',
};

export function isMarkdownType(type: string): boolean {
  return type === 'rule' || type === 'skill';
}

export function toggleArrayItem<T>(arr: T[], item: T): T[] {
  return arr.includes(item) ? arr.filter(a => a !== item) : [...arr, item];
}

export function formatError(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export const MAX_NAME_LENGTH = 40;
export const MAX_TITLE_LENGTH = 200;
export const MAX_BODY_LENGTH = 100_000;
const NAME_PATTERN = /^[a-z][a-z0-9_]*$/;

export function isValidName(name: string): boolean {
  return NAME_PATTERN.test(name) && name.length <= MAX_NAME_LENGTH;
}

export function nameError(name: string): string | null {
  if (!name.trim()) return 'Name is required.';
  if (!NAME_PATTERN.test(name)) return 'Name must be lowercase letters, digits, and underscores only.';
  if (name.length > MAX_NAME_LENGTH) return `Name must be ${MAX_NAME_LENGTH} characters or fewer.`;
  return null;
}

export function isValidRepo(r: string): boolean {
  return r === '*' || r.startsWith('/');
}
