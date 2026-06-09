import { useState, useEffect } from 'react';
import type { Paginated } from '../api';

export function usePagination<T>(
  fetcher: (limit: number, offset: number) => Promise<Paginated<T>>,
  deps: unknown[] = [],
) {
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState(10);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    setLoading(true);
    fetcher(limit, offset)
      .then(res => { setItems(res.items); setTotal(res.total); })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit, offset, ...deps]);

  return { items, setItems, total, loading, limit, offset, setLimit, setOffset };
}
