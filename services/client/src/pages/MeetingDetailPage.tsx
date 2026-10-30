import { useCallback, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import ReactMarkdown from 'react-markdown';
import { api } from '../api';
import { CopyButton } from '../components/CopyButton';
import { MeetingTranscript } from '../components/MeetingTranscript';
import { MeetingMemories } from '../components/MeetingMemories';
import { MeetingProfiles } from '../components/MeetingProfiles';
import { MeetingParticipants } from '../components/MeetingParticipants';
import { CODE_BOX } from '../components/codeBox';
import { DateCell } from '../components/table';
import { usePolling } from '../hooks/usePolling';
import { useApiRead } from '../hooks/useApiRead';
import { safeHttpUrl } from '../utils/links';
import { MeetingProcessing } from '../components/MeetingProcessing';
import { DetailPageHeader } from '../components/DetailPageHeader';
import { MeetingLabels } from '../components/MeetingLabels';
import type { MeetingTranscript as Transcript, MeetingMemories as Memories, MeetingProfiles as Personas } from '../api';

export function MeetingDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [processingVersion, setProcessingVersion] = useState(0);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [memories, setMemories] = useState<Memories | null>(null);
  const [personas, setPersonas] = useState<Personas | null>(null);
  const [labelsBusy, setLabelsBusy] = useState(false);
  const [statement, setStatement] = useState<{ meetingId: string; id: string; text: string } | null>(null);
  const [participantsBusy, setParticipantsBusy] = useState(false);
  const processingChanged = useCallback(() => setProcessingVersion(previous => previous + 1), []);
  const read = useCallback(() => {
    if (!id) return Promise.reject(new Error('Meeting not found'));
    return api.meetings.get(id);
  }, [id]);
  const { data: meeting, loading, error, refresh: load } = useApiRead(read);
  usePolling(() => load({ showLoading: false }), { enabled: Boolean(id) && !labelsBusy });

  const sourceUrl = meeting ? safeHttpUrl(meeting.source_url) : null;

  return (
    <div>
      <DetailPageHeader backTo={{ label: 'meetings', path: '/meetings' }} editing={false} saving={false}
        showActions={false} onNavigateBack={() => navigate('/meetings')} />
      <div className="page-header profiles-header">
        <h2 className="page-title">{meeting ? meeting.title || 'Untitled meeting' : 'Meeting'}</h2>
      </div>
      {error && (
        <div className="card" role="alert">
          <p>{meeting ? 'Could not refresh this meeting. Your current view and drafts are retained.' : `Could not load meeting: ${error}`}</p>
          <button className="btn" onClick={() => load({ showLoading: false })}>Retry</button>
        </div>
      )}
      {loading && !meeting ? <div className="loading">Loading meeting...</div> : meeting && (
        <>
          <nav aria-label="Meeting sections" className="flex-wrap" style={{ marginBottom: 16 }}>
            {['Summary', 'Participants', 'Transcript', 'Memories', 'Profiles'].map(label => <a className="text-link" key={label} href={`#meeting-${label.toLowerCase()}`}>{label}</a>)}
          </nav>
          <MeetingLabels key={`labels-${meeting.id}`} meeting={meeting} onReload={() => load({ showLoading: false })} onBusyChange={setLabelsBusy} />
          <MeetingProcessing key={`processing-${meeting.id}`} meetingId={meeting.id} transcript={transcript} memories={memories} personas={personas} onChanged={processingChanged} disabled={participantsBusy || labelsBusy} />
          <details className="card"><summary>Meeting details · {meeting.source_name}</summary>
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
          </details>
          <div id="meeting-summary" className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h3 className="section-title" style={{ margin: 0 }}>Summary</h3>
              <CopyButton text={meeting.summary_markdown || meeting.summary_text} />
            </div>
            <div className="markdown-content"><ReactMarkdown>{meeting.summary_markdown || meeting.summary_text}</ReactMarkdown></div>
          </div>
          <MeetingParticipants key={meeting.id} meetingId={meeting.id} onChanged={processingChanged} statement={statement?.meetingId === meeting.id ? statement : null} onStatementClosed={() => setStatement(null)} onBusyChange={setParticipantsBusy} />
          <MeetingTranscript key={`transcript-${meeting.id}`} meetingId={meeting.id} refreshVersion={processingVersion} onState={setTranscript}
            assignmentDisabled={participantsBusy}
            onAssign={segment => { setStatement({ meetingId: meeting.id, id: segment.id, text: segment.text }); document.getElementById('meeting-participants')?.scrollIntoView({ behavior: 'smooth' }); }} />
          <MeetingMemories key={`memories-${meeting.id}`} meetingId={meeting.id} refreshVersion={processingVersion} onState={setMemories} />
          <MeetingProfiles key={`profiles-${meeting.id}`} meetingId={meeting.id} refreshVersion={processingVersion} onState={setPersonas} />
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
