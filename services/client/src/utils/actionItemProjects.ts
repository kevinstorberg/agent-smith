export type ProjectScope =
  { kind: 'all' } | { kind: 'unassigned' } | { kind: 'named'; name: string };

export function projectScope(
  project: string,
  unassigned = false,
): ProjectScope {
  return project
    ? { kind: 'named', name: project }
    : { kind: unassigned ? 'unassigned' : 'all' };
}

export function projectScopeFields(scope: ProjectScope) {
  return {
    project: scope.kind === 'named' ? scope.name : '',
    unassigned: scope.kind === 'unassigned',
  };
}

export function projectScopeKey(scope: ProjectScope) {
  return JSON.stringify(scope);
}

export function projectLabel(name: string) {
  if (
    name.trim() !== name ||
    /\p{Cc}/u.test(name) ||
    name.startsWith('Project: ')
  )
    return `Project: ${JSON.stringify(name)}`;
  return ['all projects', 'unassigned', 'no project'].includes(
    name.toLowerCase(),
  )
    ? `Project: ${name}`
    : name;
}

export function newProjectName(value: string): string | null {
  const name = value.trim();
  return name && [...name].length <= 200 && !/\p{Cc}/u.test(value)
    ? name
    : null;
}
