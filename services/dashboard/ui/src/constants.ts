export const ALL_AGENTS = ['claude', 'codex', 'gemini'];

export const TYPE_PATHS: Record<string, string> = {
  rule: 'rules',
  skill: 'skills',
  tool: 'tools',
  hook: 'hooks',
};

export const TYPE_LABELS: Record<string, string> = {
  rule: 'Rule',
  skill: 'Skill',
  tool: 'Tool',
  hook: 'Hook',
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
