import { useEffect, useRef } from 'react';
import { POLL_INTERVAL_MS } from '../constants';

interface UsePollingOptions {
  enabled?: boolean;
  intervalMs?: number;
}

function validateInterval(intervalMs: number) {
  if (!Number.isFinite(intervalMs) || intervalMs <= 0) {
    throw new Error(`usePolling intervalMs must be a positive finite number, got ${intervalMs}`);
  }
}

export function usePolling(
  callback: () => void | Promise<void>,
  { enabled = true, intervalMs = POLL_INTERVAL_MS }: UsePollingOptions = {},
) {
  validateInterval(intervalMs);

  const callbackRef = useRef(callback);
  const inFlightRef = useRef(false);

  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) return undefined;

    const tick = () => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      Promise.resolve(callbackRef.current())
        .catch(() => undefined)
        .finally(() => {
          inFlightRef.current = false;
        });
    };

    const intervalId = window.setInterval(tick, intervalMs);
    return () => window.clearInterval(intervalId);
  }, [enabled, intervalMs]);
}
