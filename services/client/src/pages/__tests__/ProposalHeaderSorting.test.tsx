import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import type { Paginated, Proposal } from '../../api';
import { api } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { proposalFixture } from '../../../browser-tests/operationsFixture';
import { ProposalsIndexPage } from '../ProposalsIndexPage';

vi.mock('../../api', () => ({
  api: {
    proposals: {
      list: vi.fn(),
      counts: vi.fn(),
      approve: vi.fn(),
      reject: vi.fn(),
      generate: vi.fn(),
    },
  },
}));

const response = (title: string): Paginated<Proposal> => ({
  items: [{ ...proposalFixture(), title }],
  total: 30,
});
const header = (name: string) =>
  screen.getByRole('columnheader', { name: new RegExp(`^${name}$`) });
const button = (name: string) => within(header(name)).getByRole('button');

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.resetAllMocks();
  vi.mocked(api.proposals.list).mockResolvedValue(response('Accepted row'));
  vi.mocked(api.proposals.counts).mockResolvedValue({
    pending: 30,
    approved: 1,
    rejected: 2,
  });
});

it.each([
  ['Title', 'title', 'title_desc'],
  ['Kind', 'kind_asc', 'kind_desc'],
  ['Action', 'action_asc', 'action_desc'],
  ['Target', 'target_asc', 'target_desc'],
  ['Created', 'newest', 'oldest'],
])(
  'toggles %s globally at page zero while preserving filters and controls',
  async (label, first, second) => {
    renderWithProviders(<ProposalsIndexPage />, {
      initialEntries: [
        '/proposals?status=pending&q=release&sort=kind_desc&offset=20&keep=1',
      ],
    });
    await screen.findByText('Accepted row');
    expect(
      screen.queryByRole('combobox', { name: 'Sort proposals' }),
    ).not.toBeInTheDocument();
    expect(
      within(header('Actions')).queryByRole('button'),
    ).not.toBeInTheDocument();
    for (const sort of [first, second]) {
      fireEvent.click(button(label));
      await waitFor(() =>
        expect(api.proposals.list).toHaveBeenLastCalledWith('pending', {
          limit: 10,
          offset: 0,
          q: 'release',
          sort,
        }),
      );
      await waitFor(() =>
        expect(header(label)).toHaveAttribute(
          'aria-sort',
          sort.endsWith('_desc') || sort === 'newest'
            ? 'descending'
            : 'ascending',
        ),
      );
    }
    expect(api.proposals.generate).not.toHaveBeenCalled();
    expect(api.proposals.approve).not.toHaveBeenCalled();
    expect(api.proposals.reject).not.toHaveBeenCalled();
    expect(api.proposals.counts).toHaveBeenCalledTimes(1);
  },
);

it('keeps accepted rows quiet and focused while disabling stale review actions and rejecting late results', async () => {
  let resolveAsc!: (value: Paginated<Proposal>) => void;
  let resolveDesc!: (value: Paginated<Proposal>) => void;
  const asc = new Promise<Paginated<Proposal>>((resolve) => {
    resolveAsc = resolve;
  });
  const desc = new Promise<Paginated<Proposal>>((resolve) => {
    resolveDesc = resolve;
  });
  vi.mocked(api.proposals.list).mockImplementation((_status, options) =>
    options?.sort === 'title'
      ? asc
      : options?.sort === 'title_desc'
        ? desc
        : Promise.resolve(response('Accepted row')),
  );
  renderWithProviders(<ProposalsIndexPage />, {
    initialEntries: ['/proposals'],
  });
  await screen.findByText('Accepted row');
  const table = screen.getByRole('table');
  const title = button('Title');
  title.focus();
  fireEvent.click(title);
  await waitFor(() =>
    expect(api.proposals.list).toHaveBeenLastCalledWith(
      'pending',
      expect.objectContaining({ sort: 'title' }),
    ),
  );
  expect(screen.getByText('Accepted row')).toBeVisible();
  expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
  expect(table).toHaveAttribute('aria-busy', 'true');
  expect(header('Title')).not.toHaveAttribute('aria-sort');
  expect(title).toHaveFocus();
  expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled();
  fireEvent.click(title);
  await waitFor(() =>
    expect(api.proposals.list).toHaveBeenLastCalledWith(
      'pending',
      expect.objectContaining({ sort: 'title_desc' }),
    ),
  );
  await act(async () => resolveDesc(response('Accepted descending')));
  await screen.findByText('Accepted descending');
  await act(async () => resolveAsc(response('Late ascending')));
  expect(screen.queryByText('Late ascending')).not.toBeInTheDocument();
  expect(table).toHaveAttribute('aria-busy', 'false');
  expect(header('Title')).toHaveAttribute('aria-sort', 'descending');
  expect(title).toHaveFocus();
  expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
});

it('retains headers through failure, announces retry, and accepts an empty result without a false active sort', async () => {
  let finish!: (value: Paginated<Proposal>) => void;
  const retry = new Promise<Paginated<Proposal>>((resolve) => {
    finish = resolve;
  });
  vi.mocked(api.proposals.list)
    .mockRejectedValueOnce(new Error('Unavailable'))
    .mockReturnValueOnce(retry);
  renderWithProviders(<ProposalsIndexPage />, {
    initialEntries: ['/proposals'],
  });
  await screen.findByRole('alert');
  expect(screen.getAllByRole('columnheader')).toHaveLength(6);
  const table = screen.getByRole('table');
  expect(table).toHaveAttribute('aria-busy', 'false');
  const title = button('Title');
  title.focus();
  fireEvent.click(title);
  await waitFor(() =>
    expect(api.proposals.list).toHaveBeenLastCalledWith(
      'pending',
      expect.objectContaining({ sort: 'title' }),
    ),
  );
  expect(table).toHaveAttribute('aria-busy', 'true');
  expect(header('Title')).not.toHaveAttribute('aria-sort');
  await act(async () => finish({ items: [], total: 0 }));
  expect(await screen.findByText('No pending proposals')).toBeVisible();
  expect(table).toHaveAttribute('aria-busy', 'false');
  expect(header('Title')).toHaveAttribute('aria-sort', 'ascending');
  expect(title).toHaveFocus();
});
