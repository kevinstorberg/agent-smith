export const MEETING_VIEWS = [['overview', 'Overview'], ['transcript', 'Transcript'], ['memories', 'Memories'], ['profiles', 'Profiles']] as const;
export type MeetingView = typeof MEETING_VIEWS[number][0];

export function transcriptTarget(hash: string): number | null {
  const match = /^#(?:transcript-)?segment-(\d+)$/.exec(hash);
  if (!match) return null;
  const index = Number(match[1]);
  return Number.isSafeInteger(index) && index >= 0 ? index : null;
}

export function meetingHashView(hash: string): MeetingView | null {
  if (hash === '#meeting-summary') return 'overview';
  if (hash === '#meeting-participants' || hash === '#meeting-transcript' || transcriptTarget(hash) !== null) return 'transcript';
  if (hash === '#meeting-memories') return 'memories';
  if (hash === '#meeting-profiles') return 'profiles';
  return null;
}

export function meetingView(tab: string | null, hash: string): MeetingView {
  return meetingHashView(hash) || MEETING_VIEWS.find(([value]) => value === tab)?.[0] || 'overview';
}
