import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, type ActionItemProposal } from '../../api';
import { useActionItemProposalDecision } from '../useActionItemProposalDecision';
import { actionItemProposal } from '../../pages/__tests__/actionItemProposalFixture';
import { deferred } from '../../pages/__tests__/actionItemFixture';
import { epicGroup } from '../../pages/__tests__/actionItemEpicFixture';
import { epicReference } from '../../utils/actionItemEpics';

const proposal = actionItemProposal();
const approved = () =>
  actionItemProposal({
    status: 'approved',
    review_outcome: 'completed',
    applied_ref: { action_item_id: 12, review_outcome: 'completed' },
  });
const placement = {
  expected_parent: epicReference(epicGroup(20, []).epic),
  destination: epicReference(epicGroup(10, []).epic),
};

beforeEach(() => {
  vi.spyOn(api.actionItemProposals, 'approve').mockResolvedValue(approved());
  vi.spyOn(api.actionItemProposals, 'reject').mockResolvedValue(
    actionItemProposal({ status: 'rejected', review_outcome: 'rejected' }),
  );
});
afterEach(() => vi.restoreAllMocks());

function renderDecision() {
  const refresh = vi.fn().mockResolvedValue(undefined);
  const onSuccess = vi.fn();
  const canStart = vi.fn().mockReturnValue(true);
  const hook = renderHook(() =>
    useActionItemProposalDecision({ refresh, onSuccess, canStart }),
  );
  return { ...hook, refresh, onSuccess, canStart };
}

describe('proposal completion decision lifecycle', () => {
  it.each([false, true])(
    'sends one completion approval with placement=%s',
    async (placed) => {
      const { result, refresh, onSuccess, canStart } = renderDecision();
      await act(async () =>
        result.current.decide(
          proposal,
          'complete',
          placed ? placement : undefined,
        ),
      );
      expect(api.actionItemProposals.approve).toHaveBeenCalledExactlyOnceWith(
        1,
        { complete: true, ...(placed ? { placement } : {}) },
      );
      expect(api.actionItemProposals.reject).not.toHaveBeenCalled();
      expect(canStart).toHaveBeenCalledWith(proposal, 'complete');
      expect(refresh).toHaveBeenCalledTimes(1);
      expect(onSuccess).toHaveBeenCalledWith(approved());
      expect(result.current.pendingId).toBeNull();
    },
  );

  it('preserves existing ordinary approval, placement approval, and rejection bodies', async () => {
    const { result } = renderDecision();
    await act(async () => result.current.decide(proposal, 'approve'));
    await act(async () =>
      result.current.decide(proposal, 'approve', placement),
    );
    await act(async () => result.current.decide(proposal, 'reject', placement));
    expect(vi.mocked(api.actionItemProposals.approve).mock.calls).toEqual([
      [1],
      [1, { placement }],
    ]);
    expect(api.actionItemProposals.reject).toHaveBeenCalledExactlyOnceWith(1);
  });

  it('retains single-flight admission through completion and canonical refresh', async () => {
    const saving = deferred<ActionItemProposal>();
    const refreshing = deferred<void>();
    vi.mocked(api.actionItemProposals.approve).mockReturnValue(saving.promise);
    const { result, refresh } = renderDecision();
    refresh.mockReturnValue(refreshing.promise);
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.decide(proposal, 'complete', placement);
    });
    expect(result.current.pendingId).toBe(1);
    await act(async () =>
      result.current.decide(proposal, 'complete', placement),
    );
    await act(async () => result.current.decide(proposal, 'reject'));
    expect(api.actionItemProposals.approve).toHaveBeenCalledTimes(1);
    expect(api.actionItemProposals.reject).not.toHaveBeenCalled();
    await act(async () => saving.resolve(approved()));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(result.current.isWriting()).toBe(true);
    expect(result.current.pendingId).toBe(1);
    await act(async () =>
      result.current.decide(proposal, 'complete', placement),
    );
    expect(api.actionItemProposals.approve).toHaveBeenCalledTimes(1);
    await act(async () => {
      refreshing.resolve();
      await pending;
    });
    expect(result.current.pendingId).toBeNull();
    expect(result.current.isWriting()).toBe(false);
  });

  it.each([409, 504])(
    'refreshes after%s without an automatic replay, then preserves complete and placement on manual retry',
    async (status) => {
      vi.mocked(api.actionItemProposals.approve).mockRejectedValueOnce(
        new ApiError('Decision was not confirmed', status),
      );
      const { result, refresh, onSuccess } = renderDecision();
      await act(async () =>
        result.current.decide(proposal, 'complete', placement),
      );
      expect(result.current.error?.message).toBe('Decision was not confirmed');
      expect(refresh).toHaveBeenCalledTimes(1);
      expect(api.actionItemProposals.approve).toHaveBeenCalledTimes(1);
      expect(onSuccess).not.toHaveBeenCalled();
      await act(async () =>
        result.current.decide(proposal, 'complete', placement),
      );
      expect(vi.mocked(api.actionItemProposals.approve).mock.calls).toEqual([
        [1, { complete: true, placement }],
        [1, { complete: true, placement }],
      ]);
      expect(onSuccess).toHaveBeenCalledTimes(1);
    },
  );

  it('rejects completion admission for stale and already-decided proposals', async () => {
    const { result, canStart, refresh } = renderDecision();
    canStart.mockReturnValue(false);
    await act(async () => result.current.decide(proposal, 'complete'));
    canStart.mockReturnValue(true);
    await act(async () => result.current.decide(approved(), 'complete'));
    expect(api.actionItemProposals.approve).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });

  it('does not refresh or publish success after unmounting an in-flight completion', async () => {
    const saving = deferred<ActionItemProposal>();
    vi.mocked(api.actionItemProposals.approve).mockReturnValue(saving.promise);
    const { result, unmount, refresh, onSuccess } = renderDecision();
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.decide(proposal, 'complete', placement);
    });
    unmount();
    await act(async () => {
      saving.resolve(approved());
      await pending;
    });
    expect(refresh).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
