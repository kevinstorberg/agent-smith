import { useState } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { MeetingSummary } from '../api';
import { Pagination } from '../components/Pagination';
import { DateCell } from '../components/table';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { makeRowClickable } from '../utils/a11y';
import { MeetingVocabulary } from '../components/MeetingVocabulary';

export function MeetingsIndexPage() {
  const navigate = useNavigate();
  const [searchText, setSearchText] = useState('');
  const [query, setQuery] = useState('');
  const { items, total, loading, error, limit, offset, setLimit, setOffset, refresh } = usePagination<MeetingSummary>(
    (pageLimit, pageOffset) => api.meetings.list({ limit: pageLimit, offset: pageOffset, q: query || undefined }),
    [query],
  );
  usePolling(() => refresh({ showLoading: false }));

  const search = (value: string) => {
    setQuery(value.trim());
    setOffset(0);
  };

  return (
    <div>
      <h2 className="page-title" style={{ marginBottom: 8 }}>Meetings</h2>
      <p className="text-muted-sm" style={{ marginBottom: 16 }}>Saved summaries from all meeting connections.</p>
      <MeetingVocabulary />

      <form className="search-bar" onSubmit={event => { event.preventDefault(); search(searchText); }}>
        <input
          aria-label="Search meetings"
          placeholder="Search titles and summaries..."
          maxLength={1000}
          value={searchText}
          onChange={event => setSearchText(event.target.value)}
        />
        <button className="btn btn-primary" type="submit">Search</button>
        {query && (
          <button className="btn" type="button" onClick={() => { setSearchText(''); search(''); }}>Clear</button>
        )}
      </form>

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
                  <td>{meeting.title || 'Untitled meeting'}</td>
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
  );
}
