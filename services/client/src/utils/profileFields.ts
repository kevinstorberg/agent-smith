import type { ProfileMetadataFields, ProfileSectionKey } from '../api';

export const PROFILE_SECTIONS: [ProfileSectionKey, string][] = [
  ['overview', 'Overview'], ['drivers', 'Drivers and motivations'], ['strengths', 'Strengths'],
  ['development_areas', 'Development areas'], ['working_style', 'Working style'], ['relationships', 'Relationships and perceptions'],
];

export const PROFILE_METADATA_FIELDS: { key: keyof ProfileMetadataFields; label: string; type?: string }[] = [
  { key: 'company', label: 'Company' }, { key: 'job_role', label: 'Job role / title' },
  { key: 'start_date', label: 'Start date', type: 'date' }, { key: 'supervisor', label: 'Supervisor' },
  { key: 'gender', label: 'Gender' }, { key: 'marital_status', label: 'Marital status' },
];

export function formatProfileCoverage(coverage: { claim_count: number; meeting_count: number }): string {
  return `${coverage.claim_count} observation${coverage.claim_count === 1 ? '' : 's'} from ${coverage.meeting_count} meeting${coverage.meeting_count === 1 ? '' : 's'}`;
}
