import { useEffect, useLayoutEffect, useRef, useState } from 'react';

interface RefreshOptions {
  showLoading?: boolean;
}
interface WriteOptions {
  pendingId?: number;
  order?: boolean;
}

export function useActionItemWrites({
  refresh,
  view,
  paused,
  editing = false,
  canStart,
  onError,
  onFinish,
}: {
  refresh: (options?: RefreshOptions) => Promise<unknown>;
  view: string;
  paused: boolean;
  editing?: boolean;
  canStart: () => boolean;
  onError: (message: string) => void;
  onFinish: () => void;
}) {
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [savingOrder, setSavingOrder] = useState(false);
  const writing = useRef(false);
  const mounted = useRef(false);
  const focus = useRef<{
    handle: HTMLButtonElement | null;
    fallback?: HTMLElement;
    view: string;
  } | null>(null);
  const latest = useRef({ refresh, view, canStart, onError, onFinish });
  useLayoutEffect(() => {
    latest.current = { refresh, view, canStart, onError, onFinish };
  });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const busy = savingOrder || pendingId !== null || editing;
  useEffect(() => {
    if (busy || paused) return;
    const captured = focus.current;
    focus.current = null;
    const target =
      captured?.view !== latest.current.view
        ? null
        : captured?.handle?.isConnected && !captured.handle.disabled
          ? captured.handle
          : captured?.fallback;
    if (
      target?.isConnected &&
      !(target instanceof HTMLButtonElement && target.disabled) &&
      document.activeElement === document.body
    )
      target.focus({ preventScroll: true });
  }, [busy, paused]);

  async function runWrite<T>(
    write: () => Promise<T>,
    fallback: string,
    options: WriteOptions = {},
  ): Promise<{ value: T } | null> {
    if (!mounted.current || writing.current || !latest.current.canStart())
      return null;
    writing.current = true;
    if (options.pendingId !== undefined) setPendingId(options.pendingId);
    if (options.order) setSavingOrder(true);
    try {
      return { value: await write() };
    } catch (failure) {
      if (mounted.current)
        latest.current.onError(
          failure instanceof Error ? failure.message : fallback,
        );
      return null;
    } finally {
      try {
        if (mounted.current)
          await latest.current.refresh({ showLoading: false });
      } finally {
        writing.current = false;
        if (mounted.current) {
          setPendingId(null);
          setSavingOrder(false);
          latest.current.onFinish();
        }
      }
    }
  }
  return { pendingId, savingOrder, busy, writing, mounted, focus, runWrite };
}
