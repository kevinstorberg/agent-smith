import { useCallback, useEffect, useRef, useState } from 'react';

export function useApiRead<T>(read: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  const requestId = useRef(0);
  const activeRead = useRef(read);

  const refresh = useCallback(async ({ showLoading = true }: { showLoading?: boolean } = {}) => {
    if (!mounted.current || activeRead.current !== read) return;
    const currentRequest = ++requestId.current;
    if (showLoading) setLoading(true);
    try {
      const result = await read();
      if (mounted.current && currentRequest === requestId.current) {
        setData(result);
        setError(null);
      }
    } catch (err) {
      if (mounted.current && currentRequest === requestId.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (mounted.current && currentRequest === requestId.current) setLoading(false);
    }
  }, [read]);

  useEffect(() => {
    mounted.current = true;
    activeRead.current = read;
    refresh();
    return () => {
      mounted.current = false;
      requestId.current += 1;
    };
  }, [read, refresh]);

  return { data, loading, error, refresh };
}
