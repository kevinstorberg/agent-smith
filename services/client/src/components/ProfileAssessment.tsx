import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { api, ApiError } from '../api';
import type { ParticipantProfile, ProfileBuildResult } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { personaOutcome } from '../utils/personaOutcome';
import { formatProfileCoverage } from '../utils/profileFields';

const STATUS: Record<string, string> = { pending: 'Waiting for an assessment update', running: 'Updating assessment', failed: 'Assessment needs attention', current: 'Assessment is current', insufficient_evidence: 'More evidence is needed' };

export function ProfileAssessment({ profile, disabled, onBusyChange, onReload }: {
  profile: ParticipantProfile; disabled: boolean; onBusyChange: (busy: boolean) => void; onReload: () => void;
}) {
  const [result, setResult] = useState<ProfileBuildResult | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const onReloadRef = useRef(onReload);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { onReloadRef.current = onReload; }, [onReload]);
  const build = useApiMutation({
    mutationFn: () => api.profiles.rebuild(profile.id, profile.revision),
    onSuccess: value => { if (mounted.current) { setResult(value); setNotice(personaOutcome(value, true).message); onReloadRef.current(); } },
    onError: failure => {
      if (!mounted.current) return;
      setNotice(failure instanceof ApiError && failure.status === 409 ? failure.message : 'The run result could not be read. Check persona job executions before trying again.');
      if (failure instanceof ApiError && failure.status === 409) onReloadRef.current();
    },
  });
  useEffect(() => { onBusyChange(build.loading); }, [build.loading, onBusyChange]);
  const canGenerate = profile.assessment?.can_generate ?? profile.claims.some(claim => claim.status !== 'rejected');
  const hasAssessment = Object.values(profile.section_notes || {}).some(Boolean);
  return <section className="card" aria-label="Assessment processing">
    <div className="page-header profiles-header"><h3 className="section-title">Assessment</h3>
      <button className="btn" disabled={disabled || build.loading || !canGenerate || profile.assessment?.status === 'running'} onClick={() => { setResult(null); setNotice(null); build.mutate(); }}>
        {build.loading ? 'Updating assessment...' : hasAssessment ? 'Refresh assessment' : 'Build assessment'}
      </button>
    </div>
    <p className="text-muted-sm">Build a cumulative assessment from this person’s saved observations. New analysis merges automatically; every change is recorded in History.</p>
    {profile.assessment && <p className="text-muted-sm">{STATUS[profile.assessment.status]} · {formatProfileCoverage(profile.assessment.coverage)}</p>}
    {!canGenerate && <p className="text-muted-sm">Link observations from meetings to give the assessment a reliable starting point.</p>}
    <p className="text-muted-sm">Uses your configured <Link className="text-link" to="/jobs">persona job</Link>. <Link className="text-link" to="/jobs/new?graph=persona">Create persona job</Link> if needed.</p>
    {profile.assessment?.error && <p className="text-muted-sm">Last attempt: {profile.assessment.error}</p>}
    {notice && <p role={build.error || (result && personaOutcome(result, true).failed) ? 'alert' : 'status'} style={{ marginTop: 12 }}>{notice}</p>}
    {result && <Link className="text-link" to={`/jobs/${result.job_id}?tab=executions${result.execution_id ? `&execution=${result.execution_id}` : ''}`}>View assessment execution{result.execution_id ? ` #${result.execution_id}` : ''}</Link>}
  </section>;
}
