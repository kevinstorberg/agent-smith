import { describe, expect, it } from 'vitest';
import { defaultView, mergeViewCookie, resolveView } from '../viewPreferences';

describe('project preference scope', () => {
  it('explicit Unassigned URLs replace a saved named project without losing other filters', () => {
    const cookie = mergeViewCookie('', 'actionItems', {
      ...defaultView('actionItems'),
      project: 'Work',
      tags: 'urgent',
      status: 'completed',
      sort: 'title',
      limit: 25,
      offset: 50,
    });
    expect(
      resolveView(
        'actionItems',
        cookie,
        new URLSearchParams('unassigned=true'),
      ),
    ).toMatchObject({
      project: '',
      unassigned: true,
      tags: 'urgent',
      status: 'completed',
      sort: 'title',
      limit: 25,
      offset: 0,
    });
  });

  it('explicit named-project URLs replace a saved Unassigned view', () => {
    const cookie = mergeViewCookie('', 'actionItems', {
      ...defaultView('actionItems'),
      unassigned: true,
      tags: 'urgent',
      status: 'completed',
      sort: 'title',
    });
    expect(
      resolveView('actionItems', cookie, new URLSearchParams('project=Other')),
    ).toMatchObject({
      project: 'Other',
      unassigned: false,
      tags: 'urgent',
      status: 'completed',
      sort: 'title',
    });
  });

  it('explicit empty project scope selects All projects rather than the saved group', () => {
    const cookie = mergeViewCookie('', 'actionItems', {
      ...defaultView('actionItems'),
      unassigned: true,
    });
    expect(
      resolveView('actionItems', cookie, new URLSearchParams('project=')),
    ).toMatchObject({ project: '', unassigned: false });
  });

  it('retains exact historical names through cookie and URL encoding', () => {
    const name = '  Legacy\nCafé / family & QA #1  ';
    const cookie = mergeViewCookie('', 'actionItems', {
      ...defaultView('actionItems'),
      project: name,
    });
    expect(
      resolveView('actionItems', cookie, new URLSearchParams()),
    ).toMatchObject({ project: name, unassigned: false });
    expect(
      resolveView('actionItems', '', new URLSearchParams({ project: name })),
    ).toMatchObject({ project: name, unassigned: false });
  });

  it('validates project lengths using Unicode characters without truncation', () => {
    const name = '🌱'.repeat(200);
    expect(
      resolveView('actionItems', '', new URLSearchParams({ project: name }))
        .project,
    ).toBe(name);
    expect(
      resolveView(
        'actionItems',
        '',
        new URLSearchParams({ project: 'x'.repeat(201) }),
      ).project,
    ).toBe('');
  });
});
