import { useLayoutEffect, useRef, useState, type RefObject } from 'react';
import {
  api,
  type ActionItemProposal,
  type ActionItemProposalPlacement,
} from '../api';
import { usePageLifetime } from './usePageLifetime';

export function useActionItemProposalDecision({
  refresh,
  onSuccess,
  canStart,
  focusFallback,
}: {
  refresh: () => Promise<unknown>;
  onSuccess: (proposal: ActionItemProposal) => void;
  canStart: (
    proposal: ActionItemProposal,
    action: 'approve' | 'reject',
  ) => boolean;
  focusFallback?: RefObject<HTMLElement | null>;
}) {
  const isCurrent = usePageLifetime();
  const writing = useRef(false);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const latest = useRef({ refresh, onSuccess, canStart });
  const focus = useRef<{
    element: HTMLElement;
    scope: HTMLElement | null;
  } | null>(null);
  const restore = useRef(false);
  useLayoutEffect(() => {
    latest.current = { refresh, onSuccess, canStart };
  });
  useLayoutEffect(() => {
    if (pendingId !== null || !restore.current) return;
    restore.current = false;
    const captured = focus.current;
    focus.current = null;
    if (!captured) return;
    const active = document.activeElement;
    if (
      active !== document.body &&
      active !== captured.element &&
      !captured.scope?.contains(active)
    )
      return;
    const target =
      captured.element.isConnected && !captured.element.matches(':disabled')
        ? captured.element
        : focusFallback?.current;
    target?.focus({ preventScroll: true });
  }, [pendingId, focusFallback]);

  async function decide(
    proposal: ActionItemProposal,
    action: 'approve' | 'reject',
    placement?: ActionItemProposalPlacement,
  ) {
    if (
      writing.current ||
      proposal.status !== 'pending' ||
      !latest.current.canStart(proposal, action)
    )
      return;
    writing.current = true;
    const element = document.activeElement;
    focus.current =
      element instanceof HTMLElement && element !== document.body
        ? {
            element,
            scope: element.closest('.action-item-proposal-decision-controls'),
          }
        : null;
    setPendingId(proposal.id);
    setError(null);
    try {
      try {
        const result =
          action === 'reject'
            ? await api.actionItemProposals.reject(proposal.id)
            : placement
              ? await api.actionItemProposals.approve(proposal.id, {
                  placement,
                })
              : await api.actionItemProposals.approve(proposal.id);
        if (isCurrent()) latest.current.onSuccess(result);
      } catch (cause) {
        if (isCurrent())
          setError(cause instanceof Error ? cause : new Error(String(cause)));
      }
      if (isCurrent()) await latest.current.refresh();
    } catch (cause) {
      if (isCurrent())
        setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      writing.current = false;
      if (isCurrent()) {
        restore.current = true;
        setPendingId(null);
      }
    }
  }
  return {
    decide,
    pendingId,
    error,
    isWriting: () => writing.current,
  };
}
