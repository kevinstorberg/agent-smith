import { useCallback, useEffect, useRef, useState } from 'react';

export function useApiRead<T>(read: () => Promise<T>, { enabled = true }: { enabled?: boolean } = {}) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [failures, setFailures] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  const active = useRef(enabled);
  const requestId = useRef(0);
  const activeRead = useRef(read);

  const refresh = useCallback(async ({ showLoading = true }: { showLoading?: boolean } = {}) => {
    if (!enabled || !active.current || !mounted.current || activeRead.current !== read) return;
    const currentRequest = ++requestId.current;
    if (showLoading) setLoading(true);
    try {
      const result = await read();
      if (mounted.current && currentRequest === requestId.current) {
        setData(result);
        setError(null);
        setFailures(0);
      }
    } catch (err) {
      if (mounted.current && currentRequest === requestId.current) {
        setError(err instanceof Error ? err.message : String(err)); setFailures(previous => previous + 1);
      }
    } finally {
      if (mounted.current && currentRequest === requestId.current) setLoading(false);
    }
  }, [read, enabled]);

  useEffect(() => {
    mounted.current = true;
    active.current = enabled;
    activeRead.current = read;
    setFailures(0);
    if (enabled) refresh(); else setLoading(false);
    return () => {
      mounted.current = false;
      requestId.current += 1;
    };
  }, [read, refresh, enabled]);

  return { data, loading, error, failures, refresh };
}
