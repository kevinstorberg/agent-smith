import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { api } from '../api';
import type { MeetingSummary } from '../api';
import { Pagination } from '../components/Pagination';
import { DateCell } from '../components/table';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { makeRowClickable } from '../utils/a11y';
import { MeetingVocabulary } from '../components/MeetingVocabulary';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { parseTags } from '../utils/tags';
import { FilterBar } from '../components/FilterBar';

export function MeetingsIndexPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const vocabularyActive = searchParams.get('tab') === 'vocabulary';
  const tabSearch = (tab: 'meetings' | 'vocabulary') => {
    const next = new URLSearchParams(searchParams);
    next.set('tab', tab);
    return `?${next}`;
  };
  const [searchText, setSearchText] = useState('');
  const debouncedQuery = useDebouncedValue(searchText.trim());
  const query = searchText.trim() ? debouncedQuery : '';
  const [labelInput, setLabelInput] = useState('');
  const [sort, setSort] = useState('newest');
  const labelText = useDebouncedValue(labelInput);
  const labels = useMemo(() => parseTags(labelText), [labelText]);
  const { items, total, loading, error, limit, offset, setLimit, setOffset, refresh } = usePagination<MeetingSummary>(
    (pageLimit, pageOffset) => api.meetings.list({ limit: pageLimit, offset: pageOffset, q: query || undefined, ...(labels.length ? { labels } : {}), sort }),
    [query, labels, sort],
  );
  usePolling(() => refresh({ showLoading: false }), { enabled: !vocabularyActive });

  return (
    <div>
      <h2 className="page-title" style={{ marginBottom: 8 }}>Meetings</h2>
      <p className="text-muted-sm" style={{ marginBottom: 16 }}>Saved summaries from all meeting connections and the vocabulary used to form memories.</p>
      <nav className="resource-tabs" aria-label="Meeting views">
        <Link id="meeting-tab-meetings" to={tabSearch('meetings')} aria-current={!vocabularyActive ? 'page' : undefined}>Meetings</Link>
        <Link id="meeting-tab-vocabulary" to={tabSearch('vocabulary')} aria-current={vocabularyActive ? 'page' : undefined}>Vocabulary</Link>
      </nav>
      <div hidden={vocabularyActive} role="region" aria-labelledby="meeting-tab-meetings">

      <FilterBar nameValue={searchText} onNameChange={setSearchText} nameLabel="Search meetings" namePlaceholder="Search titles and summaries...">
        {searchText && (
          <button className="btn" type="button" onClick={() => setSearchText('')}>Clear</button>
        )}
        <label><span className="form-label">Filter meetings by labels</span>
          <input placeholder="Labels (comma-separated)" maxLength={600}
            value={labelInput} onChange={event => setLabelInput(event.target.value)} />
        </label>
        {labelInput && <button className="btn" onClick={() => setLabelInput('')}>Clear labels</button>}
        <label><span className="form-label">Sort meetings</span>
          <select className="input" value={sort} onChange={event => setSort(event.target.value)}>
            <option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="title">Title A–Z</option>
          </select>
        </label>
      </FilterBar>

      {loading ? <div className="loading">Loading meetings...</div> : error ? (
        <div className="card" role="alert">
          <p>Could not load meetings: {error}</p>
          <button className="btn" onClick={() => refresh()}>Retry</button>
        </div>
      ) : (
        <>
          <div className="profiles-table" role="region" aria-label="Meetings list" tabIndex={0}>
          <table className="table">
            <thead>
              <tr><th>Title</th><th>Connection</th><th>Provider</th><th>Meeting date</th><th>Last updated</th></tr>
            </thead>
            <tbody>
              {items.map(meeting => (
                <tr key={meeting.id} {...makeRowClickable(() => navigate(`/meetings/${meeting.id}`))} style={{ cursor: 'pointer' }}>
                  <td>{meeting.title || 'Untitled meeting'}{Boolean(meeting.labels?.length) && <div className="flex-wrap" style={{ marginTop: 6 }}>
                    {meeting.labels!.map(label => <span className="tag tag-sm" key={label}>{label}</span>)}
                  </div>}</td>
                  <td>{meeting.source_name}</td>
                  <td>{meeting.provider}</td>
                  <td><DateCell date={meeting.meeting_start || meeting.provider_created_at} /></td>
                  <td><DateCell date={meeting.updated_at} /></td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr><td colSpan={5} className="loading">
                  {query ? 'No meetings match your search.' : 'No meeting summaries saved yet. Run your meeting import job from Jobs.'}
                </td></tr>
              )}
            </tbody>
          </table>
          </div>
          <Pagination
            total={total}
            limit={limit}
            offset={offset}
            onPageChange={setOffset}
            onLimitChange={value => { setLimit(value); setOffset(0); }}
          />
        </>
      )}
      </div>
      <div hidden={!vocabularyActive} role="region" aria-labelledby="meeting-tab-vocabulary">
        <MeetingVocabulary />
      </div>
    </div>
  );
}
