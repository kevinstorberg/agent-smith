import type { MeetingAnalysisCandidate, MeetingAnalysisCandidates } from '../src/api';
import { meetingFixture } from '../src/pages/__tests__/meetingFixture';
import { profileFixture } from '../src/pages/__tests__/profileFixture';

export function meetingAnalysisCandidate(index = 0): MeetingAnalysisCandidate {
  const stage = { status: 'done', can_reanalyze: true, blocked_reason: null, job_id: null, job_name: null,
    progress: { processed_units: 1, total_units: 1, staged_count: 1, saved_count: 1, attempts: 0, next_attempt_at: null } };
  return { id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
    title: `${meetingFixture.title} ${index + 1}`, source_name: meetingFixture.source_name,
    meeting_start: meetingFixture.meeting_start, labels: [], match_reasons: ['identified_speaker'], attribution_ready: true,
    expected: { provider: meetingFixture.provider, account_key: meetingFixture.account_key,
      source_name: meetingFixture.source_name, meeting_revision: meetingFixture.revision, transcript_hash: 'a'.repeat(64),
      participants_revision: 1, speaker_updated_at: null, profile_updated_at: null, memory_updated_at: null },
    stages: { profile: stage, memory: stage } };
}

export function meetingAnalysisCandidatesPage(url: URL, total = 27): MeetingAnalysisCandidates {
  const limit = Number(url.searchParams.get('limit') || 10);
  const offset = Number(url.searchParams.get('offset') || 0);
  return { items: Array.from({ length: Math.min(limit, Math.max(0, total - offset)) }, (_, index) => meetingAnalysisCandidate(offset + index)),
    total, profile: url.searchParams.has('profile_id')
      ? { id: profileFixture.id, revision: profileFixture.revision, display_name: profileFixture.display_name } : null };
}
