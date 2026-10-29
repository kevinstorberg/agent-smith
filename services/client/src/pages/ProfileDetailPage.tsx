import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import { api, ApiError } from '../api';
import type { ProfileSectionKey } from '../api';
import { DateCell } from '../components/table';
import { useApiRead } from '../hooks/useApiRead';
import { useApiMutation } from '../hooks/useApiMutation';
import { usePolling } from '../hooks/usePolling';
import { ProfileMetadata } from '../components/ProfileMetadata';
import { ProfileIdentity } from '../components/ProfileIdentity';
import { ProfileNotes } from '../components/ProfileNotes';
import { ProfileAssessment } from '../components/ProfileAssessment';
import { ProfileEvidence } from '../components/ProfileEvidence';
import { ProfileHistory } from '../components/ProfileHistory';
import { ProfileRelationships } from '../components/ProfileRelationships';
import { DetailPageHeader } from '../components/DetailPageHeader';

const ASSESSMENT_SECTIONS: ProfileSectionKey[] = ['drivers', 'strengths', 'development_areas', 'working_style'];
const VIEWS = [['overview', 'Overview'], ['assessment', 'Assessment'], ['relationships', 'Relationships'], ['evidence', 'Evidence']] as const;
type View = typeof VIEWS[number][0];

export function ProfileDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const selected = searchParams.get('tab');
  const view: View = selected === 'assessment' || selected === 'relationships' || selected === 'evidence' ? selected : 'overview';
  const tabSearch = (value: View) => {
    const next = new URLSearchParams(searchParams);
    next.set('tab', value);
    return `?${next}`;
  };
  const setView = (value: View) => setSearchParams(previous => {
    const next = new URLSearchParams(previous); next.set('tab', value); return next;
  });
  const [evidenceVisited, setEvidenceVisited] = useState(view === 'evidence');
  useEffect(() => { if (view === 'evidence') setEvidenceVisited(true); }, [view]);
  const read = useCallback(() => id ? api.profiles.get(id) : Promise.reject(new Error('Profile not found')), [id]);
  const { data: profile, loading, error, refresh } = useApiRead(read);
  const [notice, setNotice] = useState<string | null>(null);
  const [metadataBusy, setMetadataBusy] = useState(false);
  const [metadataEditing, setMetadataEditing] = useState(false);
  const [metadataSaving, setMetadataSaving] = useState(false);
  const metadataForm = useRef<HTMLFormElement>(null);
  const [identityBusy, setIdentityBusy] = useState(false);
  const [overviewBusy, setOverviewBusy] = useState(false);
  const [notesBusy, setNotesBusy] = useState(false);
  const [relationshipsBusy, setRelationshipsBusy] = useState(false);
  const [assessmentBusy, setAssessmentBusy] = useState(false);
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const otherBusy = overviewBusy || notesBusy || relationshipsBusy || assessmentBusy || evidenceBusy;
  useEffect(() => {
    if (profile && profile.id !== id) navigate(`/profiles/${profile.id}${searchParams.size ? `?${searchParams}` : ''}`, { replace: true });
  }, [profile, id, navigate, searchParams]);
  const reload = () => refresh({ showLoading: false });
  const deletion = useApiMutation({
    mutationFn: (revision: number) => api.profiles.remove(profile!.id, revision),
    onSuccess: () => navigate('/profiles'),
    onError: failure => {
      setNotice(failure instanceof ApiError && failure.status === 409
        ? 'This profile changed. Review the latest version and submit again.' : 'Could not delete this profile. Try again.');
      if (failure instanceof ApiError && failure.status === 409) reload();
    },
  });
  usePolling(reload, { enabled: !metadataBusy && !identityBusy && !otherBusy && !deletion.loading });
  const remove = () => {
    if (profile && confirm('Delete this participant profile? It will stay deleted and will not be recreated automatically.')) deletion.mutate(profile.revision);
  };
  const baseDisabled = metadataBusy || identityBusy || assessmentBusy || evidenceBusy || deletion.loading;

  return <div className="profile-detail">
    <div className="card profile-summary">
      <DetailPageHeader backTo={{ label: 'profiles', path: '/profiles' }} onNavigateBack={() => navigate('/profiles')}
        editing={metadataEditing} saving={metadataSaving} showActions={Boolean(profile)}
        disabled={identityBusy || otherBusy || deletion.loading || (!metadataEditing && metadataBusy)}
        onEdit={() => { setView('overview'); setMetadataEditing(true); }} onSave={() => metadataForm.current?.requestSubmit()}
        onCancel={() => setMetadataEditing(false)} onDelete={remove} />
      <div className="profile-summary-content">
        <div className="profile-summary-identity">
          <h2 className="page-title">{profile?.display_name || 'Profile'}</h2>
          {(profile?.metadata?.job_role || profile?.metadata?.company) && <p>{[profile.metadata.job_role, profile.metadata.company].filter(Boolean).join(' · ')}</p>}
          {profile?.email && <p className="text-muted-sm">{profile.email}</p>}
          {profile && <>
            <p className="text-muted-sm">{profile.identity_scope === 'email' ? 'Identity linked by email.' : profile.identity_scope === 'manual'
              ? 'Manually created profile. Link a known email or assign this person in a meeting to connect their evidence.'
              : 'Identified in this meeting only; no cross-meeting identity match.'}</p>
            <div className="profile-revision"><span>Revision {profile.revision}</span><DateCell date={profile.updated_at} /></div>
          </>}
        </div>
        {profile && <ProfileAssessment key={`assessment-${profile.id}`} profile={profile}
          disabled={metadataBusy || identityBusy || overviewBusy || notesBusy || relationshipsBusy || evidenceBusy || deletion.loading}
          onBusyChange={setAssessmentBusy} onReload={reload} />}
      </div>
    </div>
    {error && <div className="card" role="alert"><p>{profile ? 'Could not refresh this profile. Your current view and drafts are retained.' : 'Could not load this participant profile. It may be unavailable or deleted.'}</p><button className="btn" onClick={reload}>Retry</button></div>}
    {loading && !profile ? <div className="loading">Loading participant profile...</div> : profile && <>
      <nav className="resource-tabs" aria-label="Profile views">
        {VIEWS.map(([value, label]) => <Link key={value} id={`profile-tab-${value}`} to={tabSearch(value)} aria-current={view === value ? 'page' : undefined}>{label}</Link>)}
      </nav>
      {notice && <p className="card" role="alert">{notice}</p>}
      <div hidden={view !== 'overview'} role="region" aria-labelledby="profile-tab-overview">
        <ProfileNotes key={`overview-${profile.id}`} profile={profile} sectionKeys={['overview']}
          disabled={baseDisabled || notesBusy || relationshipsBusy} onBusyChange={setOverviewBusy} onReload={reload} />
        <div className="card">
          <h3 className="section-title">About this person</h3>
          <ProfileMetadata key={`metadata-${profile.id}`} profile={profile} disabled={identityBusy || otherBusy || deletion.loading}
            editing={metadataEditing} onEditingChange={setMetadataEditing} onSavingChange={setMetadataSaving} formRef={metadataForm}
            onBusyChange={setMetadataBusy} onReload={reload} />
        </div>
        <ProfileIdentity key={`identity-${profile.id}`} profile={profile} disabled={metadataBusy || otherBusy || deletion.loading}
          onBusyChange={setIdentityBusy} onReload={reload}
          onSaved={winner => { if (winner.id !== id) navigate(`/profiles/${winner.id}${tabSearch(view)}`, { replace: true }); else reload(); }} />
        <ProfileHistory key={`history-${profile.id}`} profileId={profile.id} revision={profile.revision}
          evidenceHref={tabSearch('evidence')} legacyRelationships={profile.section_notes?.relationships !== undefined ? { text: profile.section_notes.relationships, human: profile.section_evidence?.relationships?.human ?? false } : undefined} />
      </div>
      <div hidden={view !== 'assessment'} role="region" aria-labelledby="profile-tab-assessment">
        <ProfileNotes key={`sections-${profile.id}`} profile={profile} sectionKeys={ASSESSMENT_SECTIONS}
          disabled={baseDisabled || overviewBusy || relationshipsBusy} onBusyChange={setNotesBusy} onReload={reload} />
      </div>
      <div hidden={view !== 'relationships'} role="region" aria-labelledby="profile-tab-relationships">
        <ProfileRelationships key={`relationships-${profile.id}`} profile={profile} disabled={baseDisabled || overviewBusy || notesBusy}
          onBusyChange={setRelationshipsBusy} onReload={reload} />
      </div>
      <div hidden={view !== 'evidence'} role="region" aria-labelledby="profile-tab-evidence">
        {(view === 'evidence' || evidenceVisited) && <ProfileEvidence key={`evidence-${profile.id}`} profile={profile} active={view === 'evidence'}
          disabled={metadataBusy || identityBusy || overviewBusy || notesBusy || relationshipsBusy || assessmentBusy || deletion.loading}
          onBusyChange={setEvidenceBusy} onReload={reload} />}
      </div>
    </>}
  </div>;
}
