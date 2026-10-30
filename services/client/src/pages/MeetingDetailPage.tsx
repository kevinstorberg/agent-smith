import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router';
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
import { usePageVisible } from '../hooks/usePageVisible';
import { safeHttpUrl } from '../utils/links';
import { MEETING_VIEWS, meetingHashView, meetingView, transcriptTarget } from '../utils/meetingViews';
import type { MeetingView } from '../utils/meetingViews';
import { MeetingProcessing } from '../components/MeetingProcessing';
import { DetailPageHeader } from '../components/DetailPageHeader';
import { MeetingLabels } from '../components/MeetingLabels';

export function MeetingDetailPage() {
  const { id } = useParams();
  return <MeetingDetail key={id} id={id} />;
}

function MeetingDetail({ id }: { id?: string }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const visible = usePageVisible();
  const view = meetingView(searchParams.get('tab'), location.hash);
  const target = transcriptTarget(location.hash);
  const [processingVersion, setProcessingVersion] = useState(0);
  const [labelsBusy, setLabelsBusy] = useState(false);
  const [statement, setStatement] = useState<{ meetingId: string; id: string; text: string } | null>(null);
  const [participantsBusy, setParticipantsBusy] = useState(false);
  const processingChanged = useCallback(() => setProcessingVersion(previous => previous + 1), []);
  const read = useCallback(() => id ? api.meetings.get(id) : Promise.reject(new Error('Meeting not found')), [id]);
  const meetingRead = useApiRead(read, { enabled: visible });
  const readProcessing = useCallback(() => id ? api.meetings.processing(id) : Promise.reject(new Error('Meeting not found')), [id]);
  const processingRead = useApiRead(readProcessing, { enabled: visible });
  const { refresh: refreshProcessing } = processingRead;
  const { data: meeting, loading, error, refresh: load } = meetingRead;
  const processing = processingRead.data;
  usePolling(() => load({ showLoading: false }), { enabled: visible && Boolean(id) && !labelsBusy });
  usePolling(() => refreshProcessing({ showLoading: false }), { enabled: visible && processingRead.failures < 3 });
  const previousVersion = useRef(processingVersion);
  useEffect(() => {
    if (previousVersion.current !== processingVersion) {
      previousVersion.current = processingVersion;
      void refreshProcessing({ showLoading: false });
    }
  }, [processingVersion, refreshProcessing]);
  const tabLocation = (value: MeetingView, hash = meetingHashView(location.hash) ? '' : location.hash) => {
    const next = new URLSearchParams(searchParams); next.set('tab', value);
    return { search: `?${next}`, hash };
  };
  useEffect(() => {
    const hashView = meetingHashView(location.hash);
    if (hashView && hashView !== searchParams.get('tab')) {
      const next = new URLSearchParams(searchParams); next.set('tab', hashView);
      navigate({ search: `?${next}`, hash: location.hash }, { replace: true });
    }
  }, [location.hash, searchParams, navigate]);
  const focusedAnchor = useRef('');
  useEffect(() => {
    const key = `${location.key}:${location.hash}`;
    if (!visible || !meeting || target !== null || !meetingHashView(location.hash) || focusedAnchor.current === key) return;
    const element = document.getElementById(location.hash.slice(1));
    if (element) {
      element.scrollIntoView({ block: 'start' }); element.setAttribute('tabindex', '-1'); element.focus({ preventScroll: true });
      focusedAnchor.current = key;
    }
  }, [visible, meeting, location.hash, location.key, target, view]);
  const sourceUrl = meeting ? safeHttpUrl(meeting.source_url) : null;
  const transcriptActive = visible && view === 'transcript';
  return <div className="meeting-detail">
    <div className="card meeting-summary">
      <DetailPageHeader backTo={{ label: 'meetings', path: '/meetings' }} editing={false} saving={false} showActions={false} onNavigateBack={() => navigate('/meetings')} />
      <h2 className="page-title">{meeting ? meeting.title || 'Untitled meeting' : 'Meeting'}</h2>
      {meeting && <>
        <div className="meeting-summary-meta text-muted-sm"><DateCell date={meeting.meeting_start || meeting.provider_created_at} format="long" /><span>{meeting.source_name}</span>{meeting.project && <span className="tag tag-project">{meeting.project}</span>}
          {sourceUrl && <a className="text-link" href={sourceUrl} target="_blank" rel="noopener noreferrer">Open original meeting</a>}
        </div>
        <MeetingProcessing meetingId={meeting.id} transcript={processing?.transcript || null} memories={processing?.memories || null} personas={processing?.profiles || null} speakers={processing?.speakers} onChanged={processingChanged} disabled={participantsBusy || labelsBusy || Boolean(processingRead.error)} />
        {processingRead.error && <div role="alert" className="meeting-status-error"><p>Could not refresh processing status. Your current view and drafts are kept.{processingRead.failures >= 3 ? ' Automatic refresh is paused.' : ''}</p><button className="btn btn-sm" disabled={processingRead.loading} onClick={() => refreshProcessing()}>Refresh status</button></div>}
        {(participantsBusy || labelsBusy) && <p className="text-muted-sm">Finish your {participantsBusy ? 'participant changes in Transcript' : 'label changes in Overview'} before queuing other processing.</p>}
      </>}
    </div>
    {error && <div className="card" role="alert"><p>{meeting ? 'Could not refresh this meeting. Your current view and drafts are retained.' : `Could not load meeting: ${error}`}</p><button className="btn" onClick={() => load({ showLoading: false })}>Retry</button></div>}
    {loading && !meeting ? <div className="loading">Loading meeting...</div> : meeting && <>
      <nav className="resource-tabs" aria-label="Meeting views">{MEETING_VIEWS.map(([value, label]) => <Link key={value} id={`meeting-detail-tab-${value}`} to={tabLocation(value)} aria-current={view === value ? 'page' : undefined}>{label}</Link>)}</nav>
      <div hidden={view !== 'overview'} role="region" aria-labelledby="meeting-detail-tab-overview">
        {view === 'overview' && <section id="meeting-summary" className="card"><div className="participants-header"><h3 className="section-title">Summary</h3><CopyButton text={meeting.summary_markdown || meeting.summary_text} /></div><div className="markdown-content"><ReactMarkdown>{meeting.summary_markdown || meeting.summary_text}</ReactMarkdown></div></section>}
        <MeetingLabels meeting={meeting} onReload={() => load({ showLoading: false })} onBusyChange={setLabelsBusy} active={view === 'overview'} />
        {view === 'overview' && <details className="card"><summary>Meeting details · {meeting.source_name}</summary><dl className="meeting-source-details"><dt>Connection</dt><dd>{meeting.source_name}</dd><dt>Provider</dt><dd>{meeting.provider}</dd><dt>Account</dt><dd>{meeting.account_key}</dd><dt>Meeting date</dt><dd><DateCell date={meeting.meeting_start || meeting.provider_created_at} format="long" /></dd>
          {meeting.meeting_end && <><dt>Meeting end</dt><dd><DateCell date={meeting.meeting_end} format="long" /></dd></>}
          <dt>Source updated</dt><dd><DateCell date={meeting.provider_updated_at} format="long" /></dd><dt>Saved</dt><dd><DateCell date={meeting.updated_at} format="long" /></dd><dt>Revision</dt><dd>{meeting.revision}</dd>
        </dl>{Object.keys(meeting.metadata).length > 0 && <details className="meeting-raw-metadata"><summary>Additional metadata</summary><pre style={CODE_BOX}>{JSON.stringify(meeting.metadata, null, 2)}</pre></details>}</details>}
      </div>
      <div hidden={view !== 'transcript'} role="region" aria-labelledby="meeting-detail-tab-transcript">
        <MeetingParticipants meetingId={meeting.id} onChanged={processingChanged} active={transcriptActive} statement={statement} onStatementClosed={() => setStatement(null)} onBusyChange={setParticipantsBusy} />
        <MeetingTranscript meetingId={meeting.id} refreshVersion={processingVersion} active={transcriptActive} targetSegment={target} assignmentDisabled={participantsBusy} onChanged={processingChanged} onShowBeginning={() => navigate(tabLocation('transcript', '#meeting-transcript'))} onAssign={segment => { setStatement({ meetingId: meeting.id, id: segment.id, text: segment.text }); navigate(tabLocation('transcript', '#meeting-participants')); }} />
      </div>
      <div hidden={view !== 'memories'} role="region" aria-labelledby="meeting-detail-tab-memories"><MeetingMemories meetingId={meeting.id} refreshVersion={processingVersion} active={visible && view === 'memories'} onChanged={processingChanged} /></div>
      <div hidden={view !== 'profiles'} role="region" aria-labelledby="meeting-detail-tab-profiles"><MeetingProfiles meetingId={meeting.id} refreshVersion={processingVersion} active={visible && view === 'profiles'} onChanged={processingChanged} /></div>
    </>}
  </div>;
}
