import type { MeetingSummary } from '../../api';

export const meetingFixture: MeetingSummary = {
  id: '9d85d0c6-bf5d-41b9-9a7d-c1e082180b8e',
  provider: 'granola',
  account_key: 'personal',
  external_id: 'note-1',
  source_name: 'personal',
  project: null,
  title: 'Product planning',
  summary_text: 'Discussed the next release.',
  summary_markdown: '## Decisions\n\nShip the next release.',
  source_url: 'https://example.com/meetings/note-1',
  metadata: { attendees: ['Alex'] },
  provider_created_at: '2026-10-20T10:00:00Z',
  provider_updated_at: '2026-10-20T11:00:00Z',
  meeting_start: '2026-10-20T10:00:00Z',
  meeting_end: '2026-10-20T10:30:00Z',
  revision: 2,
  first_seen_at: '2026-10-20T11:01:00Z',
  updated_at: '2026-10-20T11:01:00Z',
};
