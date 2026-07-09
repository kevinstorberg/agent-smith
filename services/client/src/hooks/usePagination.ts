import { useState, useEffect, useCallback, useRef } from 'react';
import type { Paginated } from '../api';

interface RefreshOptions {
  showLoading?: boolean;
}

export function usePagination<T>(
  fetcher: (limit: number, offset: number) => Promise<Paginated<T>>,
  deps: unknown[] = [],
) {
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState(10);
  const [offset, setOffset] = useState(0);
  const mountedRef = useRef(false);
  const requestIdRef = useRef(0);
  const fetcherRef = useRef(fetcher);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
    };
  }, []);

  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const refresh = useCallback(async ({ showLoading = true }: RefreshOptions = {}) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    if (showLoading) setLoading(true);

    try {
      const res = await fetcherRef.current(limit, offset);
      if (mountedRef.current && requestId === requestIdRef.current) {
        setItems(res.items);
        setTotal(res.total);
      }
    } finally {
      if (mountedRef.current && requestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, [limit, offset]);

  useEffect(() => {
    refresh({ showLoading: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, ...deps]);

  return { items, setItems, total, loading, limit, offset, setLimit, setOffset, refresh };
}
