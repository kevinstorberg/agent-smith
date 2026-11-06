import {
  useState,
  useEffect,
  useLayoutEffect,
  useCallback,
  useRef,
} from 'react';
import type { SetStateAction } from 'react';
import type { Paginated } from '../api';

interface RefreshOptions {
  showLoading?: boolean;
}

export interface PaginationState {
  limit: number;
  offset: number;
}
export interface PaginationOptions {
  page?: PaginationState;
  onPageChange?: (page: PaginationState) => void;
  enabled?: boolean;
  clampOffset?: boolean;
}

function sameFilters(left: unknown[], right: unknown[]): boolean {
  return (
    left.length === right.length &&
    left.every((value, index) => Object.is(value, right[index]))
  );
}

export function usePagination<T>(
  fetcher: (limit: number, offset: number) => Promise<Paginated<T>>,
  deps: unknown[] = [],
  initialLimit = 10,
  options: PaginationOptions = {},
) {
  if (options.page && !options.onPageChange)
    throw new Error('Controlled pagination requires onPageChange');
  const [items, setItems] = useState<T[]>([]);
  const [resultView, setResultView] = useState<{
    filters: unknown[];
    limit: number;
    offset: number;
  } | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [internalPage, setInternalPage] = useState({
    limit: initialLimit,
    offset: 0,
  });
  const { limit, offset } = options.page ?? internalPage;
  const enabled = options.enabled !== false;
  const mountedRef = useRef(false);
  const requestIdRef = useRef(0);
  const fetcherRef = useRef(fetcher);
  const filtersRef = useRef(deps);
  const live = useRef({ filters: deps, limit, offset, options, enabled });
  useLayoutEffect(() => {
    live.current = { filters: deps, limit, offset, options, enabled };
  });

  const updatePage = useCallback(
    (change: (page: PaginationState) => PaginationState) => {
      const current = live.current;
      const next = change({ limit: current.limit, offset: current.offset });
      if (
        !Number.isSafeInteger(next.limit) ||
        next.limit <= 0 ||
        !Number.isSafeInteger(next.offset) ||
        next.offset < 0
      )
        throw new Error(
          'Pagination requires a positive integer limit and nonnegative integer offset',
        );
      if (next.limit === current.limit && next.offset === current.offset)
        return;
      requestIdRef.current += 1;
      live.current = { ...current, ...next };
      if (current.options.page) current.options.onPageChange!(next);
      else setInternalPage(next);
    },
    [],
  );
  const setLimit = useCallback(
    (value: SetStateAction<number>) =>
      updatePage((page) => ({
        limit: typeof value === 'function' ? value(page.limit) : value,
        offset: 0,
      })),
    [updatePage],
  );
  const setOffset = useCallback(
    (value: SetStateAction<number>) =>
      updatePage((page) => ({
        ...page,
        offset: typeof value === 'function' ? value(page.offset) : value,
      })),
    [updatePage],
  );

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

  const refresh = useCallback(
    async ({ showLoading = true }: RefreshOptions = {}) => {
      if (!live.current.enabled) return;
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      if (showLoading) setLoading(true);
      const requestFilters = filtersRef.current;
      const currentRequest = () =>
        mountedRef.current &&
        requestId === requestIdRef.current &&
        live.current.enabled &&
        live.current.limit === limit &&
        live.current.offset === offset &&
        sameFilters(live.current.filters, requestFilters);

      try {
        const res = await fetcherRef.current(limit, offset);
        if (currentRequest()) {
          if (
            live.current.options.clampOffset &&
            offset > 0 &&
            offset >= res.total
          ) {
            setLoading(true);
            setOffset(
              res.total ? Math.floor((res.total - 1) / limit) * limit : 0,
            );
            return;
          }
          setItems(res.items);
          setResultView({ filters: requestFilters, limit, offset });
          setTotal(res.total);
          setError(null);
        }
      } catch (err) {
        if (currentRequest()) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (currentRequest()) {
          setLoading(false);
        }
      }
    },
    [limit, offset, setOffset],
  );

  useEffect(() => {
    const filtersChanged =
      deps.length !== filtersRef.current.length ||
      deps.some((value, index) => !Object.is(value, filtersRef.current[index]));
    filtersRef.current = deps;
    if (!enabled) {
      requestIdRef.current += 1;
      setLoading(true);
      return;
    }
    if (filtersChanged && offset !== 0 && !live.current.options.page) {
      requestIdRef.current += 1;
      setOffset(0);
      return;
    }
    refresh({ showLoading: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, enabled, ...deps]);

  const dataCurrent =
    enabled &&
    resultView !== null &&
    resultView.limit === limit &&
    resultView.offset === offset &&
    sameFilters(deps, resultView.filters);
  return {
    items,
    setItems,
    total,
    loading,
    initialLoading: loading && resultView === null,
    error,
    dataCurrent,
    limit,
    offset,
    setLimit,
    setOffset,
    refresh,
  };
}
