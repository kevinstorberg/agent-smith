import { columnSortOptions } from './utils/tableSorting';

export const ALL_AGENTS = ['claude', 'codex', 'gemini'] as const;
export const POLL_INTERVAL_MS = 15_000;
export const PAGE_LIMITS = [10, 25, 50] as const;
export type PageLimit = (typeof PAGE_LIMITS)[number];
export const HARNESS_SORT_COLUMNS = {
  order: { ascending: 'manual', descending: 'manual_desc' },
  name: { ascending: 'name', descending: 'name_desc' },
  project: { ascending: 'project_asc', descending: 'project_desc' },
  enabled: { ascending: 'enabled_asc', descending: 'enabled_desc' },
  clone_as_skill: {
    ascending: 'clone_as_skill_asc',
    descending: 'clone_as_skill_desc',
  },
  agents: { ascending: 'agents_asc', descending: 'agents_desc' },
  configs: { ascending: 'config_count_asc', descending: 'config_count_desc' },
  version: { ascending: 'version_asc', descending: 'version_desc' },
  updated: {
    ascending: 'updated_asc',
    descending: 'updated',
    defaultDirection: 'descending',
  },
} as const;
export const HARNESS_SORT_OPTIONS = [
  ...columnSortOptions(HARNESS_SORT_COLUMNS),
  { value: 'newest', label: 'Newest first' },
] as const;
export function harnessSortOptions(type: string) {
  return HARNESS_SORT_OPTIONS.filter(
    (option) =>
      type === 'rule' ||
      (option.value !== HARNESS_SORT_COLUMNS.clone_as_skill.ascending &&
        option.value !== HARNESS_SORT_COLUMNS.clone_as_skill.descending),
  );
}
export const AUDIT_STATUSES = ['pending', 'success', 'error'] as const;
export const PROPOSAL_STATUSES = ['pending', 'approved', 'rejected'] as const;
export const AUDIT_SORT_OPTIONS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
  { value: 'duration', label: 'Longest duration' },
] as const;
export const PROPOSAL_SORT_OPTIONS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
  { value: 'title', label: 'Title' },
] as const;
export const EVAL_SUITE_SORT_OPTIONS = [
  { value: 'name', label: 'Name' },
  { value: 'updated', label: 'Recently updated' },
  { value: 'newest', label: 'Newest first' },
] as const;
const UPDATED_AT_SORT_OPTIONS = [
  { value: 'updated_at_desc', label: 'Updated: newest' },
  { value: 'updated_at_asc', label: 'Updated: oldest' },
] as const;
export const MEMORY_LIST_SORT_OPTIONS = [
  { value: 'created_at_desc', label: 'Newest first' },
  { value: 'created_at_asc', label: 'Oldest first' },
  ...UPDATED_AT_SORT_OPTIONS,
] as const;
export const MEMORY_SEARCH_SORT_OPTIONS = [
  { value: 'relevance', label: 'Relevance' },
  ...MEMORY_LIST_SORT_OPTIONS,
] as const;
export const MEETING_SORT_OPTIONS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
  { value: 'title', label: 'Title A–Z' },
] as const;
export const VOCABULARY_DEFINITIONS = [
  { value: 'all', label: 'All terms' },
  { value: 'defined', label: 'With definition' },
  { value: 'undefined', label: 'Without definition' },
] as const;
export const VOCABULARY_SORT_OPTIONS = [
  { value: 'term', label: 'Term A–Z' },
  { value: 'updated', label: 'Recently updated' },
] as const;

export const ACTION_ITEM_STATUSES = [
  ['open', 'Open'],
  ['completed', 'Completed'],
  ['all', 'All'],
] as const;
export type ActionItemStatus = (typeof ACTION_ITEM_STATUSES)[number][0];
const ACTION_ITEM_COMMON_SORTS = [
  { value: 'newest', label: 'Newest' },
  { value: 'updated', label: 'Updated: newest' },
  { value: 'title', label: 'Title A–Z' },
] as const;
export const ACTION_ITEM_SORT_OPTIONS = [
  { value: 'manual', label: 'Manual order' },
  { value: 'completed', label: 'Completed: newest' },
  ...ACTION_ITEM_COMMON_SORTS,
] as const;
export function actionItemSortOptions(status: ActionItemStatus) {
  return ACTION_ITEM_SORT_OPTIONS.filter((option) =>
    option.value === 'manual'
      ? status === 'open'
      : option.value === 'completed'
        ? status === 'completed'
        : true,
  );
}
export function defaultActionItemSort(status: ActionItemStatus) {
  return status === 'open'
    ? 'manual'
    : status === 'completed'
      ? 'completed'
      : 'newest';
}
export const PROFILE_SORT_OPTIONS = [
  { value: 'starred_name_asc', label: 'Starred, name A–Z' },
  { value: 'created_at_desc', label: 'Newest profiles' },
  { value: 'created_at_asc', label: 'Oldest profiles' },
  { value: 'name_asc', label: 'Name A–Z' },
  { value: 'name_desc', label: 'Name Z–A' },
  ...UPDATED_AT_SORT_OPTIONS,
] as const;
export const CHAT_STATUSES = [
  { value: 'all', label: 'All rooms' },
  { value: 'open', label: 'Open' },
  { value: 'closed', label: 'Closed' },
] as const;
export const CHAT_SORT_OPTIONS = [
  { value: 'updated', label: 'Recently updated' },
  { value: 'newest', label: 'Newest first' },
  { value: 'name', label: 'Topic A–Z' },
] as const;
export const RESULT_SORT_COLUMNS = {
  time: {
    ascending: 'oldest',
    descending: 'newest',
    defaultDirection: 'descending',
  },
  category: { ascending: 'category_asc', descending: 'category_desc' },
  scenario: { ascending: 'scenario_asc', descending: 'scenario_desc' },
  model: { ascending: 'model_asc', descending: 'model_desc' },
  threshold: { ascending: 'threshold_asc', descending: 'threshold_desc' },
  scores: {
    ascending: 'score_asc',
    descending: 'score',
    defaultDirection: 'descending',
  },
} as const;
export const RESULT_SORT_OPTIONS = columnSortOptions(RESULT_SORT_COLUMNS);

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
  return arr.includes(item) ? arr.filter((a) => a !== item) : [...arr, item];
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
  if (!NAME_PATTERN.test(name))
    return 'Name must be lowercase letters, digits, and underscores only.';
  if (name.length > MAX_NAME_LENGTH)
    return `Name must be ${MAX_NAME_LENGTH} characters or fewer.`;
  return null;
}

export function isValidRepo(r: string): boolean {
  return r === '*' || r.startsWith('/');
}
