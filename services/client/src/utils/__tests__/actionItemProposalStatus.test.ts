import { describe, expect, it } from 'vitest';
import { PROPOSAL_STATUSES } from '../../constants';
import { defaultView, mergeViewCookie, resolveView } from '../viewPreferences';

describe('Action Item proposal status preferences', () => {
  it('restores superseded only for Action Items, keeping harness statuses separate', () => {
    const cookie = mergeViewCookie('', 'actionItemProposals', {
      ...defaultView('actionItemProposals'),
      status: 'superseded',
    });
    expect(
      resolveView('actionItemProposals', cookie, new URLSearchParams()).status,
    ).toBe('superseded');
    expect(
      resolveView('proposals', cookie, new URLSearchParams('status=superseded'))
        .status,
    ).toBe('pending');
    expect(PROPOSAL_STATUSES).toEqual(['pending', 'approved', 'rejected']);
  });
});
