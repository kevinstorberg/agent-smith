import { describe, expect, it } from 'vitest';
import { meetingView, transcriptTarget } from '../meetingViews';

describe('meeting URL views', () => {
  it.each(['unknown', '', null])('defaults an invalid tab to Overview: %s', tab => {
    expect(meetingView(tab, '#unrelated')).toBe('overview');
  });
  it('lets existing meeting anchors select their view and leaves unrelated hashes alone', () => {
    expect(meetingView('overview', '#meeting-profiles')).toBe('profiles');
    expect(meetingView('memories', '#meeting-participants')).toBe('transcript');
    expect(meetingView('transcript', '#unrelated')).toBe('transcript');
  });
  it('accepts the actual and legacy statement anchors and rejects unsafe offsets', () => {
    expect(transcriptTarget('#transcript-segment-650')).toBe(650);
    expect(transcriptTarget('#segment-0')).toBe(0);
    expect(meetingView(null, '#segment-5')).toBe('transcript');
    for (const hash of ['#segment--1', '#segment-1.5', '#segment-9007199254740992', '#segment-1-extra']) expect(transcriptTarget(hash)).toBeNull();
  });
});
