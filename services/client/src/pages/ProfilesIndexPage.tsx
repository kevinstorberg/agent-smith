import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { api, ApiError } from '../api';
import type { ProfileSummary } from '../api';
import { Pagination } from '../components/Pagination';
import { BadgeCell, DateCell } from '../components/table';
import { ProfileStar } from '../components/ProfileStar';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { makeRowClickable } from '../utils/a11y';
import { parseTags } from '../utils/tags';
import { useApiMutation } from '../hooks/useApiMutation';
import { PROFILE_SCOPE_LABELS } from '../utils/profiles';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { PersonaJob } from '../components/PersonaJob';

const SORT_OPTIONS = [
  ['starred_name_asc', 'Starred first · Name A–Z'],
  ['created_at_desc', 'Newest profiles'], ['created_at_asc', 'Oldest profiles'],
  ['name_asc', 'Name A–Z'], ['name_desc', 'Name Z–A'],
  ['updated_at_desc', 'Recently updated'], ['updated_at_asc', 'Least recently updated'],
];

export function ProfilesIndexPage() {
  const navigate = useNavigate();
  const [searchText, setSearchText] = useState('');
  const debouncedQuery = useDebouncedValue(searchText.trim());
  const query = searchText.trim() ? debouncedQuery : '';
  const [tagText, setTagText] = useState('');
  const debouncedTags = useDebouncedValue(tagText);
  const tags = useMemo(() => parseTags(debouncedTags), [debouncedTags]);
  const [starredOnly, setStarredOnly] = useState(false);
  const [sort, setSort] = useState('starred_name_asc');
  const [notice, setNotice] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [createNotice, setCreateNotice] = useState<string | null>(null);
  const create = useApiMutation({
    mutationFn: () => api.profiles.create({ display_name: name.trim(), ...(email.trim() ? { email: email.trim() } : {}) }),
    onSuccess: profile => navigate(`/profiles/${profile.id}`),
    onError: failure => setCreateNotice(failure instanceof ApiError && failure.status === 409
      ? failure.message : 'Could not create this profile. Try again.'),
  });
  const { items, total, loading, error, limit, offset, setLimit, setOffset, refresh } = usePagination<ProfileSummary>(
    (pageLimit, pageOffset) => api.profiles.list({ limit: pageLimit, offset: pageOffset, q: query || undefined,
      sort, ...(tags.length ? { tags } : {}), ...(starredOnly ? { starred: true } : {}) }),
    [query, tags, starredOnly, sort],
  );
  const star = useApiMutation({
    mutationFn: (profile: ProfileSummary) => api.profiles.update(profile.id, { expected_revision: profile.revision, starred: !profile.starred }),
    onSuccess: () => { setNotice(null); refresh({ showLoading: false }); },
    onError: failure => {
      setNotice(failure instanceof ApiError && failure.status === 409 ? 'This profile changed. Review the refreshed profile and try again.' : 'Could not change the star. Try again.');
      refresh({ showLoading: false });
    },
  });
  usePolling(() => refresh({ showLoading: false }), { enabled: !star.loading });

  return (
    <div>
      <div className="page-header profiles-header">
        <h2 className="page-title">Profiles</h2>
        <div className="profile-header-actions"><PersonaJob onChanged={() => refresh({ showLoading: false })} />
        <button className="btn btn-primary" disabled={creating} onClick={() => { setCreating(true); setName(''); setEmail(''); setCreateNotice(null); }}>New profile</button></div>
      </div>
      <p className="text-muted-sm" style={{ marginBottom: 16 }}>Manage people and their evidence from your meeting history.</p>
      {creating && <form aria-label="New profile" className="card profile-create" onSubmit={event => {
        event.preventDefault();
        if (!name.trim()) { setCreateNotice('A profile name is required.'); return; }
        create.mutate();
      }}>
        <h3>New profile</h3>
        <div>
          <label className="form-label" htmlFor="new-profile-name">Name</label>
          <input id="new-profile-name" className="input" value={name} maxLength={200} required onChange={event => setName(event.target.value)} />
        </div>
        <div>
          <label className="form-label" htmlFor="new-profile-email">Email</label>
          <input id="new-profile-email" className="input" type="email" value={email} maxLength={320} onChange={event => setEmail(event.target.value)} />
          <p className="text-muted-sm">Optional. A known email links future meetings to this person.</p>
        </div>
        {createNotice && <p role="alert">{createNotice}</p>}
        <div className="flex-wrap">
          <button className="btn btn-primary" type="submit" disabled={create.loading}>{create.loading ? 'Creating...' : 'Create profile'}</button>
          <button className="btn" type="button" disabled={create.loading} onClick={() => setCreating(false)}>Cancel</button>
        </div>
      </form>}
      <div className="profile-filters">
        <div><label className="form-label" htmlFor="profile-query">Search profiles</label>
          <div className="profile-search-input"><input id="profile-query" className="input" placeholder="Name, nickname or email" maxLength={1000}
            value={searchText} onChange={event => setSearchText(event.target.value)} />
            {searchText && <button className="btn" type="button" onClick={() => setSearchText('')}>Clear</button>}</div>
        </div>
        <div><label className="form-label" htmlFor="profile-filter-tags">Filter by tags</label>
          <input id="profile-filter-tags" className="input" placeholder="Comma-separated tags" value={tagText} onChange={event => setTagText(event.target.value)} />
        </div>
        <div><label className="form-label" htmlFor="profile-sort">Sort</label>
          <select id="profile-sort" className="input" value={sort} onChange={event => { setSort(event.target.value); setOffset(0); }}>
            {SORT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
        <label className="checkbox-label profile-starred-filter"><input className="form-checkbox" type="checkbox" checked={starredOnly} onChange={event => { setStarredOnly(event.target.checked); setOffset(0); }} /> Starred only</label>
      </div>
      {tags.length > 0 && <p className="text-muted-sm">Matches all tags: {tags.join(', ')}</p>}
      {notice && <p role="alert" className="card">{notice}</p>}
      {loading ? <div className="loading">Loading profiles...</div> : error ? (
        <div className="card" role="alert">
          <p>Could not load profiles. Try again.</p>
          <button className="btn" onClick={() => refresh()}>Retry</button>
        </div>
      ) : (
        <>
          <div className="profiles-table" role="region" aria-label="Profiles list" tabIndex={0}>
          <table className="table">
            <thead><tr><th>Star</th><th>Name</th><th>Email</th><th>Identity</th><th>Tags</th><th>Meetings</th><th>Last updated</th></tr></thead>
            <tbody>
              {items.map(profile => <tr key={profile.id} {...makeRowClickable(() => navigate(`/profiles/${profile.id}`))} style={{ cursor: 'pointer' }}>
                <td><ProfileStar name={profile.display_name} starred={profile.starred} disabled={star.loading} onClick={() => star.mutate(profile)} /></td>
                <td>{profile.display_name}
                  {(profile.metadata?.job_role || profile.metadata?.company) && <p className="text-muted-sm">{[profile.metadata.job_role, profile.metadata.company].filter(Boolean).join(' · ')}</p>}
                </td>
                <td>{profile.email || '—'}{(profile.emails?.length || 0) > 1 && <p className="text-muted-sm">+{profile.emails!.length - 1} more</p>}</td>
                <td>{PROFILE_SCOPE_LABELS[profile.identity_scope]}</td>
                <td><BadgeCell items={profile.tags} /></td>
                <td>{profile.meeting_count}</td>
                <td><DateCell date={profile.updated_at} /></td>
              </tr>)}
              {items.length === 0 && <tr><td colSpan={7} className="loading">
                {query || tags.length || starredOnly ? 'No profiles match your search.' : 'No profiles saved yet. Create one or run the persona job to review saved meeting transcripts.'}
              </td></tr>}
            </tbody>
          </table>
          </div>
          <Pagination total={total} limit={limit} offset={offset} onPageChange={setOffset}
            onLimitChange={value => { setLimit(value); setOffset(0); }} />
        </>
      )}
    </div>
  );
}
