import { useCallback, useEffect, useId, useState } from 'react';
import { api } from '../api';
import type { ProfileSummary } from '../api';
import { useApiRead } from '../hooks/useApiRead';
import { useRefreshSignal } from '../hooks/useRefreshSignal';
import { useDebouncedValue } from '../hooks/useDebouncedValue';

interface Props {
  label: string; selectionLabel: string; value: string; onSelect: (profile: ProfileSummary | null) => void;
  excludeId?: string; disabled?: boolean; limit?: number; emptyLabel?: string;
  refreshVersion?: number; onResults?: (items: ProfileSummary[]) => void;
  selectedLabel?: string;
  preserveSelectionOnSearch?: boolean;
}

export function ProfilePicker({ label, selectionLabel, value, onSelect, excludeId, disabled = false, limit = 25, emptyLabel = 'Select a profile', refreshVersion, onResults, selectedLabel, preserveSelectionOnSearch = false }: Props) {
  const id = useId();
  const [text, setText] = useState('');
  const debouncedQuery = useDebouncedValue(text.trim());
  const query = text.trim() ? debouncedQuery : '';
  const read = useCallback(() => api.profiles.list({ q: query || undefined, limit }), [query, limit]);
  const { data, loading, error, refresh } = useApiRead(read);
  useRefreshSignal(refreshVersion, refresh);
  useEffect(() => { if (data) onResults?.(data.items); }, [data, onResults]);
  return <div className="profile-picker">
    <label className="form-label" htmlFor={id}>{label}</label>
    <div className="search-bar">
      <input id={id} value={text} maxLength={1000} disabled={disabled} onChange={event => { setText(event.target.value); if (!preserveSelectionOnSearch) onSelect(null); }}
        onKeyDown={event => { if (event.key === 'Enter') event.preventDefault(); }} />
    </div>
    {error ? <div role="alert">Could not load profiles. <button type="button" className="btn" onClick={() => refresh()}>Retry</button></div> : <>
      <select className="input" aria-label={selectionLabel} disabled={disabled || loading} value={value}
        onChange={event => onSelect(data?.items.find(profile => profile.id === event.target.value) || null)}>
        <option value="">{loading ? 'Loading profiles...' : emptyLabel}</option>
        {value && !data?.items.some(profile => profile.id === value) && <option value={value}>{selectedLabel || 'Selected profile'}</option>}
        {data?.items.filter(profile => profile.id !== excludeId).map(profile => <option key={profile.id} value={profile.id}>
          {profile.display_name}{profile.email ? ` · ${profile.email}` : ''}
        </option>)}
      </select>
      {!loading && data?.items.length === 0 && <p className="text-muted-sm">No profiles found. Try a different name or email.</p>}
      {data && data.total > data.items.length && <p className="text-muted-sm">Showing the first {data.items.length}. Refine your search to find another profile.</p>}
    </>}
  </div>;
}
