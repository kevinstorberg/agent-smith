import { useCallback } from 'react';
import { Link, useParams } from 'react-router';
import ReactMarkdown from 'react-markdown';
import { api } from '../api';
import { CopyButton } from '../components/CopyButton';
import { MeetingTranscript } from '../components/MeetingTranscript';
import { MeetingMemories } from '../components/MeetingMemories';
import { CODE_BOX } from '../components/codeBox';
import { DateCell } from '../components/table';
import { usePolling } from '../hooks/usePolling';
import { useApiRead } from '../hooks/useApiRead';

function sourceLink(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}

export function MeetingDetailPage() {
  const { id } = useParams();
  const read = useCallback(() => {
    if (!id) return Promise.reject(new Error('Meeting not found'));
    return api.meetings.get(id);
  }, [id]);
  const { data: meeting, loading, error, refresh: load } = useApiRead(read);
  usePolling(() => load({ showLoading: false }), { enabled: Boolean(id) });

  const sourceUrl = meeting ? sourceLink(meeting.source_url) : null;

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">{loading || error ? 'Meeting' : meeting?.title || 'Untitled meeting'}</h2>
        <Link className="btn" to="/meetings">Back to meetings</Link>
      </div>
      {loading ? <div className="loading">Loading meeting...</div> : error ? (
        <div className="card" role="alert">
          <p>Could not load meeting: {error}</p>
          <button className="btn" onClick={() => load()}>Retry</button>
        </div>
      ) : meeting && (
        <>
          <div className="card">
            <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '8px 16px', margin: 0 }}>
              <dt>Connection</dt><dd style={{ margin: 0 }}>{meeting.source_name}</dd>
              <dt>Provider</dt><dd style={{ margin: 0 }}>{meeting.provider}</dd>
              <dt>Account</dt><dd style={{ margin: 0 }}>{meeting.account_key}</dd>
              {meeting.project && <><dt>Project</dt><dd style={{ margin: 0 }}>{meeting.project}</dd></>}
              <dt>Meeting date</dt><dd style={{ margin: 0 }}><DateCell date={meeting.meeting_start || meeting.provider_created_at} format="long" /></dd>
              {meeting.meeting_end && <><dt>Meeting end</dt><dd style={{ margin: 0 }}><DateCell date={meeting.meeting_end} format="long" /></dd></>}
              <dt>Source updated</dt><dd style={{ margin: 0 }}><DateCell date={meeting.provider_updated_at} format="long" /></dd>
              <dt>Saved</dt><dd style={{ margin: 0 }}><DateCell date={meeting.updated_at} format="long" /></dd>
              <dt>Revision</dt><dd style={{ margin: 0 }}>{meeting.revision}</dd>
            </dl>
            {sourceUrl && <p><a href={sourceUrl} target="_blank" rel="noopener noreferrer">Open original meeting</a></p>}
          </div>
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h3 className="section-title" style={{ margin: 0 }}>Summary</h3>
              <CopyButton text={meeting.summary_markdown || meeting.summary_text} />
            </div>
            <div className="markdown-content"><ReactMarkdown>{meeting.summary_markdown || meeting.summary_text}</ReactMarkdown></div>
          </div>
          <MeetingTranscript key={meeting.id} meetingId={meeting.id} />
          <MeetingMemories key={`memories-${meeting.id}`} meetingId={meeting.id} />
          {Object.keys(meeting.metadata).length > 0 && (
            <details className="card">
              <summary>Additional metadata</summary>
              <pre style={CODE_BOX}>{JSON.stringify(meeting.metadata, null, 2)}</pre>
            </details>
          )}
        </>
      )}
    </div>
  );
}
