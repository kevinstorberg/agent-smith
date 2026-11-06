import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { ProfilesIndexPage } from '../ProfilesIndexPage';
import { profileFixture } from './profileFixture';
import type { ProfileSummary } from '../../api';

vi.mock('../../api', async (original) => ({
  ...(await original<typeof import('../../api')>()),
  api: {
    profiles: { list: vi.fn(), update: vi.fn(), create: vi.fn() },
    jobs: { forGraph: vi.fn(), runNow: vi.fn() },
  },
}));
import { api } from '../../api';

const row: ProfileSummary = {
  ...profileFixture,
  claim_count: 4,
  meeting_count: 2,
  created_at: '2026-01-01T00:00:00Z',
};
const page = (name = 'Alex', total = 25) => ({
  items: [{ ...row, display_name: name }],
  total,
});
const pairs = [
  ['Star', 'starred_asc', 'starred_desc', 'starred_desc'],
  ['Name', 'name_asc', 'name_desc', 'name_asc'],
  ['Email', 'email_asc', 'email_desc', 'email_asc'],
  ['Identity', 'identity_asc', 'identity_desc', 'identity_asc'],
  ['Tags', 'tags_asc', 'tags_desc', 'tags_asc'],
  ['Meetings', 'meeting_count_asc', 'meeting_count_desc', 'meeting_count_desc'],
  ['Last updated', 'updated_at_asc', 'updated_at_desc', 'updated_at_desc'],
] as const;

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.clearAllMocks();
  vi.mocked(api.profiles.list).mockReset().mockResolvedValue(page());
  vi.mocked(api.profiles.update).mockReset().mockResolvedValue(profileFixture);
  vi.mocked(api.jobs.forGraph).mockResolvedValue({ items: [], total: 0 });
});

describe('Profile header sorting', () => {
  it('does not present an accepted-empty result as a new query result while that read is pending', async () => {
    vi.mocked(api.profiles.list).mockResolvedValueOnce({ items: [], total: 0 });
    renderWithProviders(<ProfilesIndexPage />, {
      initialEntries: ['/profiles'],
    });
    await screen.findByRole('status');
    let finish!: (value: ReturnType<typeof page>) => void;
    vi.mocked(api.profiles.list).mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Search profiles' }), {
      target: { value: 'new query' },
    });
    await waitFor(() =>
      expect(api.profiles.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: 'new query' }),
      ),
    );
    expect(screen.queryByText(/No profiles saved yet/)).not.toBeInTheDocument();
    expect(
      screen.queryByText('No profiles match your search.'),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('Loading profiles...')).not.toBeInTheDocument();
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getAllByRole('columnheader')).toHaveLength(7);
    await act(async () => finish({ items: [], total: 0 }));
    expect(
      await screen.findByText('No profiles match your search.'),
    ).toBeVisible();
  });
  it.each(pairs)(
    'toggles %s globally from page zero without a sort dropdown',
    async (label, ascending, descending, first) => {
      renderWithProviders(<ProfilesIndexPage />, {
        initialEntries: ['/profiles?q=Alex&tags=team&limit=10&offset=10'],
      });
      await screen.findByText('Alex');
      expect(
        screen.queryByRole('combobox', { name: 'Sort' }),
      ).not.toBeInTheDocument();
      const header = screen.getByRole('columnheader', { name: label });
      const button = within(header).getByRole('button');
      fireEvent.click(button);
      await waitFor(() =>
        expect(api.profiles.list).toHaveBeenLastCalledWith({
          q: 'Alex',
          tags: ['team'],
          sort: first,
          limit: 10,
          offset: 0,
        }),
      );
      await waitFor(() =>
        expect(header).toHaveAttribute(
          'aria-sort',
          first === ascending ? 'ascending' : 'descending',
        ),
      );
      fireEvent.click(button);
      await waitFor(() =>
        expect(api.profiles.list).toHaveBeenLastCalledWith(
          expect.objectContaining({
            sort: first === ascending ? descending : ascending,
          }),
        ),
      );
      expect(api.profiles.update).not.toHaveBeenCalled();
      expect(api.profiles.create).not.toHaveBeenCalled();
    },
  );

  it('keeps focus, retained rows and a creation draft while only the current response accepts sort state', async () => {
    renderWithProviders(<ProfilesIndexPage />, {
      initialEntries: ['/profiles'],
    });
    await screen.findByText('Alex');
    fireEvent.click(screen.getByRole('button', { name: 'New profile' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), {
      target: { value: 'Unsaved person' },
    });
    let finishAsc!: (value: ReturnType<typeof page>) => void;
    let finishDesc!: (value: ReturnType<typeof page>) => void;
    vi.mocked(api.profiles.list)
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finishAsc = resolve;
        }),
      )
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finishDesc = resolve;
        }),
      );
    const header = screen.getByRole('columnheader', {
      name: 'Name',
    });
    const button = within(header).getByRole('button');
    button.focus();
    fireEvent.click(button);
    expect(button).toHaveFocus();
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true');
    expect(screen.queryByText('Loading profiles...')).not.toBeInTheDocument();
    expect(screen.getByText('Alex')).toBeVisible();
    expect(document.querySelector('[aria-sort]')).toBeNull();
    expect(screen.getByRole('button', { name: 'Star Alex' })).toBeDisabled();
    fireEvent.click(button);
    await act(async () => finishDesc(page('Current descending', 40)));
    await screen.findByText('Current descending');
    await act(async () => finishAsc(page('Stale ascending', 99)));
    expect(screen.queryByText('Stale ascending')).not.toBeInTheDocument();
    expect(header).toHaveAttribute('aria-sort', 'descending');
    expect(screen.getByText('Showing 1–10 of 40')).toBeVisible();
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue(
      'Unsaved person',
    );
    expect(button).toHaveFocus();
  });

  it('keeps empty headers operable and clears busy on failure while showing busy on explicit retry', async () => {
    vi.mocked(api.profiles.list).mockResolvedValueOnce({ items: [], total: 0 });
    renderWithProviders(<ProfilesIndexPage />, {
      initialEntries: ['/profiles'],
    });
    const empty = await screen.findByRole('status');
    expect(empty.closest('table')).toBeNull();
    expect(screen.getAllByRole('columnheader')).toHaveLength(7);
    vi.mocked(api.profiles.list).mockRejectedValueOnce(
      new Error('Synthetic read failure'),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Email' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'false');
    let finish!: (value: ReturnType<typeof page>) => void;
    vi.mocked(api.profiles.list).mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true');
    await act(async () => finish(page()));
    expect(await screen.findByText('Alex')).toBeVisible();
  });
});
