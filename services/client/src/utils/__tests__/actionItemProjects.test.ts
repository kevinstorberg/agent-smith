import { describe, expect, it } from 'vitest';
import { newProjectName, projectLabel } from '../actionItemProjects';

describe('project names and navigation labels', () => {
  it('keeps exact project names distinct from built-ins and generated prefixes', () => {
    const names = [
      'Work',
      'work',
      'Unassigned',
      'All projects',
      'Project: Unassigned',
      'Project: All projects',
      '  legacy\nname  ',
      JSON.stringify('  legacy\nname  '),
    ];
    const labels = names.map(projectLabel);
    expect(new Set(labels).size).toBe(names.length);
    expect(labels).not.toContain('All projects');
    expect(labels).not.toContain('Unassigned');
    expect(projectLabel('Work')).toBe('Work');
    expect(projectLabel('work')).toBe('work');
  });

  it('validates new names by Unicode characters and rejects controls before trimming', () => {
    expect(newProjectName('  Work  ')).toBe('Work');
    expect(newProjectName('🌱'.repeat(200))).toBe('🌱'.repeat(200));
    expect(newProjectName('🌱'.repeat(201))).toBeNull();
    expect(newProjectName('\nWork')).toBeNull();
    expect(newProjectName('Work\t')).toBeNull();
  });
});
