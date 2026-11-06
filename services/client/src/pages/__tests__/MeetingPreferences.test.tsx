import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useLocation } from 'react-router';
import { renderWithProviders } from '../../test-utils';
import { MeetingsIndexPage } from '../MeetingsIndexPage';
import { api } from '../../api';
import {
  defaultView,
  mergeViewCookie,
  readViewCookie,
} from '../../utils/viewPreferences';

vi.mock('../../api', () => ({
  api: {
    meetings: {
      list: vi.fn(),
      vocabulary: {
        list: vi.fn(),
        get: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
        remove: vi.fn(),
      },
    },
  },
}));
beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.clearAllMocks();
  vi.mocked(api.meetings.list).mockResolvedValue({ items: [], total: 100 });
  vi.mocked(api.meetings.vocabulary.list).mockResolvedValue({
    items: [],
    total: 100,
  });
});
function Location() {
  return <output aria-label="URL search">{useLocation().search}</output>;
}
function savedViews() {
  const cookie = mergeViewCookie('', 'meetings', {
    ...defaultView('meetings'),
    q: 'meeting query',
    labels: 'release',
    sort: 'title',
    limit: 25,
    offset: 50,
  });
  return mergeViewCookie(cookie, 'vocabulary', {
    ...defaultView('vocabulary'),
    q: 'vocabulary query',
    definition: 'defined',
    sort: 'updated',
    limit: 50,
    offset: 50,
  });
}

describe('Meetings and Vocabulary preference boundaries', () => {
  it('restores each active view before requesting and keeps shared URL criteria from leaking across tab links', async () => {
    document.cookie = savedViews();
    renderWithProviders(
      <>
        <MeetingsIndexPage />
        <Location />
      </>,
      { initialEntries: ['/meetings?keep=1'] },
    );
    await waitFor(() => expect(api.meetings.list).toHaveBeenCalledTimes(1));
    expect(api.meetings.list).toHaveBeenCalledWith({
      q: 'meeting query',
      labels: ['release'],
      sort: 'title',
      limit: 25,
      offset: 50,
    });
    expect(api.meetings.vocabulary.list).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Meeting date' }));
    await waitFor(() =>
      expect(api.meetings.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'date_desc', offset: 0 }),
      ),
    );
    const meetingReads = vi.mocked(api.meetings.list).mock.calls.length;
    fireEvent.click(screen.getByRole('link', { name: 'Vocabulary' }));
    await waitFor(() =>
      expect(api.meetings.vocabulary.list).toHaveBeenCalledTimes(1),
    );
    expect(api.meetings.vocabulary.list).toHaveBeenCalledWith({
      q: 'vocabulary query',
      definition: 'defined',
      sort: 'updated',
      limit: 50,
      offset: 50,
    });
    expect(api.meetings.list).toHaveBeenCalledTimes(meetingReads);
    expect(
      new URLSearchParams(
        screen.getByLabelText('URL search').textContent || '',
      ).get('keep'),
    ).toBe('1');
    expect(
      screen.getByRole('textbox', { name: 'Search vocabulary' }),
    ).toHaveValue('vocabulary query');
    fireEvent.change(
      screen.getByRole('combobox', { name: 'Sort vocabulary' }),
      { target: { value: 'term' } },
    );
    await waitFor(() =>
      expect(api.meetings.vocabulary.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'term', offset: 0 }),
      ),
    );
    fireEvent.click(screen.getByRole('link', { name: 'Meetings' }));
    await waitFor(() =>
      expect(api.meetings.list).toHaveBeenLastCalledWith(
        expect.objectContaining({
          q: 'meeting query',
          sort: 'date_desc',
          offset: 0,
        }),
      ),
    );
    expect(
      readViewCookie(document.cookie).find(
        (entry) => entry.key === 'vocabulary',
      )?.values,
    ).toMatchObject({ q: 'vocabulary query', definition: 'defined' });
  });

  it('does not let an inactive meeting response clamp or overwrite the active Vocabulary page', async () => {
    let finishOld!: (value: { items: []; total: number }) => void;
    vi.mocked(api.meetings.list).mockReturnValueOnce(
      new Promise((resolve) => {
        finishOld = resolve;
      }),
    );
    document.cookie = savedViews();
    renderWithProviders(<MeetingsIndexPage />, {
      initialEntries: ['/meetings'],
    });
    expect(api.meetings.list).toHaveBeenCalledWith(
      expect.objectContaining({ offset: 50 }),
    );
    fireEvent.click(screen.getByRole('link', { name: 'Vocabulary' }));
    await waitFor(() =>
      expect(api.meetings.vocabulary.list).toHaveBeenCalledTimes(1),
    );
    await act(async () => finishOld({ items: [], total: 0 }));
    expect(api.meetings.vocabulary.list).toHaveBeenCalledTimes(1);
    expect(api.meetings.vocabulary.list).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 50, offset: 50 }),
    );
    expect(
      readViewCookie(document.cookie).find((entry) => entry.key === 'meetings')
        ?.values,
    ).toMatchObject({ q: 'meeting query', limit: 25, offset: 50 });
  });

  it('honors explicit empty and invalid Vocabulary URL values while the mounted Meetings controller stays inactive', async () => {
    document.cookie = savedViews();
    renderWithProviders(<MeetingsIndexPage />, {
      initialEntries: [
        '/meetings?tab=vocabulary&q=&definition=&sort=invalid&limit=25&offset=50',
      ],
    });
    await waitFor(() =>
      expect(api.meetings.vocabulary.list).toHaveBeenCalledTimes(1),
    );
    expect(api.meetings.vocabulary.list).toHaveBeenCalledWith({
      q: '',
      definition: undefined,
      sort: 'term',
      limit: 25,
      offset: 50,
    });
    expect(api.meetings.list).not.toHaveBeenCalled();
    expect(
      readViewCookie(document.cookie).find((entry) => entry.key === 'meetings')
        ?.values,
    ).toMatchObject({
      q: 'meeting query',
      labels: 'release',
      sort: 'title',
      offset: 50,
    });
  });
});
