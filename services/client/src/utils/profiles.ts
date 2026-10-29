import type { ParticipantProfile } from '../api';

export const PROFILE_SCOPE_LABELS: Record<ParticipantProfile['identity_scope'], string> = {
  email: 'Email',
  meeting: 'Meeting only',
  manual: 'Manual',
};
