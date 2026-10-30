import type { ProfileMetadataFields, ProfileMetadataOptions, ProfileSectionKey } from '../api';

export const PROFILE_SECTIONS: [ProfileSectionKey, string][] = [
  ['overview', 'Overview'], ['drivers', 'Drivers and motivations'], ['strengths', 'Strengths'],
  ['development_areas', 'Development areas'], ['working_style', 'Working style'], ['relationships', 'Relationships and perceptions'],
];

type MetadataField = { key: keyof ProfileMetadataFields; label: string; type?: 'date' }
  | { key: keyof ProfileMetadataOptions; label: string; type: 'select' };
export const PROFILE_METADATA_FIELDS: MetadataField[] = [
  { key: 'company', label: 'Company' }, { key: 'job_role', label: 'Job role / title' },
  { key: 'start_date', label: 'Start date', type: 'date' }, { key: 'supervisor', label: 'Supervisor' },
  { key: 'gender', label: 'Gender', type: 'select' }, { key: 'marital_status', label: 'Marital status', type: 'select' },
];

export function formatProfileCoverage(coverage: { claim_count: number; meeting_count: number }): string {
  return `${coverage.claim_count} observation${coverage.claim_count === 1 ? '' : 's'} from ${coverage.meeting_count} meeting${coverage.meeting_count === 1 ? '' : 's'}`;
}
