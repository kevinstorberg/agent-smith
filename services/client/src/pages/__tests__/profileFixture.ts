import type { ParticipantProfile, ProfileRelationshipCard } from '../../api';

export const metadataOptionsFixture = {
  gender: ['Male', 'Female', 'Non-binary', 'Other'],
  marital_status: ['Single', 'Married', 'Divorced', 'Separated', 'Widowed', 'Domestic partnership', 'Other'],
};

export const relationshipCardFixture: ProfileRelationshipCard = {
  id: 'profile:b813c24e-e32a-4440-b6da-dfe39771bf46', name: 'Jordan',
  profile_id: 'b813c24e-e32a-4440-b6da-dfe39771bf46',
  notes: 'Alex values Jordan’s judgment and seeks clear delivery commitments.', label: 'colleague',
  version: 'a'.repeat(64), human: false, status: 'supported',
  coverage: { claim_count: 2, meeting_count: 1 },
  evidence_links: [{ profile_id: 'b1bb54a0-60ec-44f8-a9ec-82e3456ee637', target_id: 'b813c24e-e32a-4440-b6da-dfe39771bf46', count: 2 }],
};

export const profileFixture: ParticipantProfile = {
  id: 'b1bb54a0-60ec-44f8-a9ec-82e3456ee637',
  display_name: 'Alex',
  email: 'alex@example.test',
  identity_scope: 'email',
  revision: 1,
  deleted: false,
  updated_at: '2026-10-28T12:00:00Z',
  tags: [],
  starred: false,
  aliases: [],
  relationship_cards: [],
  relationship_unassigned: null,
  claims: [{
    id: '97221ea0-a995-42c6-90c0-d242fb2ddd54',
    category: 'perception', epistemic: 'inference', confidence: 'medium',
    content: 'Alex appears concerned about Jordan’s delivery timeline.',
    rationale: 'Alex asked Jordan to confirm a delivery date.',
    target_id: 'b813c24e-e32a-4440-b6da-dfe39771bf46', target_name: 'Jordan',
    evidence: [{ segment_id: 'segment-650', quote: 'Jordan, can you confirm the delivery date?' }],
    meeting_id: '9d85d0c6-bf5d-41b9-9a7d-c1e082180b8e',
    source_url: 'https://example.test/meetings/one',
    status: 'active', correction: null,
  }],
};
