import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigationType, useSearchParams } from 'react-router';
import { defaultView, mergeViewCookie, parseViewField, resolveView, viewPath } from '../utils/viewPreferences';
import type { ViewKey, ViewSettings } from '../utils/viewPreferences';
import type { PaginationOptions, PaginationState } from './usePagination';

export interface ViewCookieStore { read: () => string; write: (assignment: string) => void; secure: boolean }
const browserCookies: ViewCookieStore = {
  read: () => document.cookie,
  write: assignment => { document.cookie = assignment; },
  get secure() { return window.location.protocol === 'https:'; },
};

interface ViewSnapshot<K extends ViewKey> {
  identity: string;
  locationKey: string;
  search: string;
  values: ViewSettings[K];
  pending: string[];
}

function readCookies(store: ViewCookieStore): string {
  try { return store.read(); } catch { return ''; }
}

export function useViewPreferences<K extends ViewKey>(key: K, { scope, active = true, cookieStore = browserCookies }: {
  scope?: string; active?: boolean; cookieStore?: ViewCookieStore;
} = {}) {
  const location = useLocation();
  const navigationType = useNavigationType();
  const [, setSearchParams] = useSearchParams();
  const identity = JSON.stringify([key, scope ?? null, location.pathname]);
  const matched = active && location.pathname === viewPath(key);
  const initialize = (): ViewSnapshot<K> => ({
    identity, locationKey: location.key, search: location.search, pending: [],
    values: resolveView(key, readCookies(cookieStore), new URLSearchParams(location.search), scope),
  });
  const [saved, setSaved] = useState(initialize);
  let current = saved;
  if (saved.identity !== identity) {
    current = initialize();
    setSaved(current);
  } else if (saved.locationKey !== location.key || saved.search !== location.search) {
    const ownUpdate = navigationType === 'REPLACE' && saved.pending.includes(location.search);
    current = ownUpdate ? { ...saved, locationKey: location.key, search: location.search,
      pending: saved.pending.at(-1) === location.search ? [] : saved.pending.filter(search => search !== location.search) } : initialize();
    setSaved(current);
  }
  const latest = useRef({ snapshot: current, key, scope, matched });
  useLayoutEffect(() => { latest.current = { snapshot: current, key, scope, matched }; });

  useEffect(() => {
    if (!matched) return;
    try {
      // Re-reading reduces screen-to-screen clobbering; simultaneous tabs remain best-effort last-writer-wins.
      cookieStore.write(mergeViewCookie(cookieStore.read(), key, current.values, { scope, secure: cookieStore.secure }));
    } catch { /* Browser cookie restrictions must not disable live controls. */ }
  }, [cookieStore, current.values, key, matched, scope]);

  const update = useCallback((patch: Partial<ViewSettings[K]>, resetOffset: boolean) => {
    const latestView = latest.current;
    if (!latestView.matched || latestView.snapshot.identity !== identity) return;
    const previous = latestView.snapshot;
    const values = { ...previous.values, ...patch, ...(resetOffset ? { offset: 0 } : {}) };
    const search = new URLSearchParams(previous.pending.at(-1) ?? previous.search);
    for (const field of Object.keys(patch) as (keyof ViewSettings[K])[]) search.set(String(field), String(values[field]));
    if (resetOffset) search.set('offset', '0');
    const target = search.size ? `?${search}` : '';
    const next = { ...previous, values, pending: [...previous.pending, target].slice(-32) };
    latest.current = { ...latestView, snapshot: next };
    setSaved(next);
    setSearchParams(search, { replace: true });
  }, [identity, setSearchParams]);

  const setField = useCallback(<F extends keyof ViewSettings[K]>(field: F, value: ViewSettings[K][F]) => {
    const patch: Partial<ViewSettings[K]> = {};
    patch[field] = value;
    update(patch, field !== 'offset');
  }, [update]);
  const reset = useCallback(() => update(defaultView(key), false), [key, update]);
  const onPageChange = useCallback((page: PaginationState) => update({
    limit: parseViewField(key, 'limit', page.limit), offset: page.offset,
  } as Partial<ViewSettings[K]>, false), [key, update]);
  const pagination = useMemo<PaginationOptions>(() => ({
    page: { limit: current.values.limit, offset: current.values.offset }, onPageChange, clampOffset: true,
  }), [current.values.limit, current.values.offset, onPageChange]);
  return { values: current.values, setField, reset, pagination };
}
