import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  screen,
  fireEvent,
  waitFor,
  act,
  within,
} from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { useLocation } from 'react-router';
import { MeetingsIndexPage } from '../MeetingsIndexPage';
import { meetingFixture } from './meetingFixture';

const mockNavigate = vi.fn();

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../../api', async (original) => ({
  ...(await original<typeof import('../../api')>()),
  api: {
    meetings: {
      list: vi.fn(),
      vocabulary: {
        list: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
        remove: vi.fn(),
      },
    },
  },
}));
import { api } from '../../api';

const mockList = vi.mocked(api.meetings.list);
const meetings = [
  meetingFixture,
  {
    ...meetingFixture,
    id: 'other-id',
    source_name: 'team',
    title: 'Team retrospective',
  },
];
const term = {
  id: 'term-1',
  term: 'LTV',
  definition: 'Lifetime value',
  revision: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function Location() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.pathname}
      {location.search}
    </output>
  );
}

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.clearAllMocks();
  mockList.mockReset();
  mockList.mockResolvedValue({ items: meetings, total: 2 });
  vi.mocked(api.meetings.vocabulary.list).mockResolvedValue({
    items: [],
    total: 0,
  });
});

describe('MeetingsIndexPage', () => {
  afterEach(() => vi.useRealTimers());

  it('refreshes the same filtered meeting page at 15 seconds without hiding rows', async () => {
    vi.useFakeTimers();
    mockList.mockResolvedValue({ items: meetings, total: 25 });
    await act(async () => {
      renderWithProviders(<MeetingsIndexPage />, {
        initialEntries: ['/meetings?q=release&sort=updated'],
      });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    });
    const lastParams = mockList.mock.calls.at(-1)![0];
    expect(lastParams).toMatchObject({ q: 'release', offset: 10 });
    mockList.mockClear().mockReturnValueOnce(new Promise(() => {}));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(14_999);
    });
    expect(mockList).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(mockList).toHaveBeenCalledExactlyOnceWith(lastParams);
    expect(screen.getByText('Product planning')).toBeVisible();
    expect(screen.queryByText('Loading meetings...')).not.toBeInTheDocument();
  });
  it('keeps search, labels and sort controls available during loading and empty results', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<MeetingsIndexPage />, {
      initialEntries: ['/meetings'],
    });
    expect(
      screen.getByRole('textbox', { name: 'Search meetings' }),
    ).toBeVisible();
    expect(
      screen.getByRole('textbox', { name: 'Filter meetings by labels' }),
    ).toBeVisible();
    expect(screen.getByRole('button', { name: 'Title' })).toBeVisible();
    expect(
      screen.queryByRole('combobox', { name: 'Sort meetings' }),
    ).not.toBeInTheDocument();
    await screen.findByText(
      'No meeting summaries saved yet. Run your meeting import job from Jobs.',
    );
    expect(screen.getByRole('button', { name: 'Meeting date' })).toBeVisible();
  });

  it('requests a new server sort from the first page', async () => {
    mockList.mockResolvedValue({ items: meetings, total: 25 });
    renderWithProviders(<MeetingsIndexPage />, {
      initialEntries: ['/meetings'],
    });
    await screen.findByText('Product planning');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 10 }),
      ),
    );
    mockList.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Title' }));
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    expect(mockList).toHaveBeenCalledWith(
      expect.objectContaining({ offset: 0, sort: 'title' }),
    );
  });

  it('opens Vocabulary from its URL and preserves unrelated query parameters when switching views', async () => {
    vi.mocked(api.meetings.vocabulary.list).mockResolvedValue({
      items: [term],
      total: 1,
    });
    renderWithProviders(
      <>
        <MeetingsIndexPage />
        <Location />
      </>,
      { initialEntries: ['/meetings?tab=vocabulary&source=work'] },
    );
    expect(
      await screen.findByRole('button', { name: 'Edit LTV' }),
    ).toBeVisible();
    expect(screen.getByRole('link', { name: 'Vocabulary' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(
      screen.queryByRole('textbox', { name: 'Search meetings' }),
    ).not.toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole('link', { name: 'Meetings' }));
    });
    expect(
      screen.getByRole('textbox', { name: 'Search meetings' }),
    ).toBeVisible();
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/meetings?tab=meetings&source=work',
    );
    expect(
      screen.queryByRole('button', { name: 'Edit LTV' }),
    ).not.toBeInTheDocument();
  });

  it('retains meeting search, pagination and an unsaved vocabulary edit across tab changes', async () => {
    const filteredPage = {
      items: [{ ...meetingFixture, title: 'Filtered release meeting' }],
      total: 25,
    };
    let resolveSearch!: (response: typeof filteredPage) => void;
    const searchResponse = new Promise<typeof filteredPage>((resolve) => {
      resolveSearch = resolve;
    });
    mockList.mockImplementation((params) =>
      params?.q === 'release'
        ? searchResponse
        : Promise.resolve({ items: meetings, total: 25 }),
    );
    vi.mocked(api.meetings.vocabulary.list).mockResolvedValue({
      items: [term],
      total: 1,
    });
    renderWithProviders(<MeetingsIndexPage />, {
      initialEntries: ['/meetings'],
    });
    await screen.findByText('Product planning');
    fireEvent.change(screen.getByRole('textbox', { name: 'Search meetings' }), {
      target: { value: 'release' },
    });
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith({
        limit: 10,
        offset: 0,
        q: 'release',
        sort: 'newest',
      }),
    );
    expect(screen.queryByText('Loading meetings...')).not.toBeInTheDocument();
    expect(screen.getByText('Product planning')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    await act(async () => resolveSearch(filteredPage));
    expect(await screen.findByText('Filtered release meeting')).toBeVisible();
    expect(screen.getByText('Showing 1–10 of 25')).toBeVisible();
    fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith({
        limit: 10,
        offset: 10,
        q: 'release',
        sort: 'newest',
      }),
    );
    expect(await screen.findByText('Showing 11–20 of 25')).toBeVisible();
    await act(async () => {
      fireEvent.click(screen.getByRole('link', { name: 'Vocabulary' }));
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Edit LTV' }));
    fireEvent.change(screen.getByLabelText('Meaning / definition (optional)'), {
      target: { value: 'My definition draft' },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('link', { name: 'Meetings' }));
    });
    expect(
      screen.getByRole('textbox', { name: 'Search meetings' }),
    ).toHaveValue('release');
    expect(await screen.findByText('Showing 11–20 of 25')).toBeVisible();
    expect(mockList).toHaveBeenLastCalledWith({
      limit: 10,
      offset: 10,
      q: 'release',
      sort: 'newest',
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('link', { name: 'Vocabulary' }));
    });
    expect(
      screen.getByLabelText('Meaning / definition (optional)'),
    ).toHaveValue('My definition draft');
    expect(api.meetings.vocabulary.update).not.toHaveBeenCalled();
  });

  it('renders meeting topics and filters them while typing from the first page', async () => {
    mockList.mockResolvedValue({
      items: [{ ...meetingFixture, labels: ['product', 'roadmapping'] }],
      total: 1,
    });
    renderWithProviders(<MeetingsIndexPage />, {
      initialEntries: ['/meetings'],
    });
    expect(await screen.findByText('roadmapping')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Filter meetings by labels'), {
      target: { value: 'product, roadmapping' },
    });
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith({
        limit: 10,
        offset: 0,
        q: undefined,
        labels: ['product', 'roadmapping'],
        sort: 'newest',
      }),
    );
  });
  it('shows summaries from multiple connections without a source or device filter', async () => {
    renderWithProviders(<MeetingsIndexPage />, {
      initialEntries: ['/meetings'],
    });

    expect(await screen.findByText('Product planning')).toBeInTheDocument();
    expect(screen.getByText('Team retrospective')).toBeInTheDocument();
    expect(screen.getByText('personal')).toBeInTheDocument();
    expect(screen.getByText('team')).toBeInTheDocument();
    expect(mockList).toHaveBeenCalledWith({
      limit: 10,
      offset: 0,
      q: undefined,
      sort: 'newest',
    });
  });

  it('opens the selected summary with keyboard navigation', async () => {
    renderWithProviders(<MeetingsIndexPage />, {
      initialEntries: ['/meetings'],
    });
    const title = await screen.findByText('Product planning');
    fireEvent.keyDown(title.closest('tr')!, { key: 'Enter' });

    expect(mockNavigate).toHaveBeenCalledWith(`/meetings/${meetingFixture.id}`);
  });

  it('searches and clears while keeping pagination on the server', async () => {
    mockList.mockResolvedValue({ items: meetings, total: 25 });
    renderWithProviders(<MeetingsIndexPage />, {
      initialEntries: ['/meetings'],
    });
    await screen.findByText('Product planning');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith({
        limit: 10,
        offset: 10,
        q: undefined,
        sort: 'newest',
      }),
    );

    fireEvent.change(screen.getByLabelText('Search meetings'), {
      target: { value: ' release ' },
    });
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith({
        limit: 10,
        offset: 0,
        q: 'release',
        sort: 'newest',
      }),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith({
        limit: 10,
        offset: 0,
        q: undefined,
        sort: 'newest',
      }),
    );
  });

  it('distinguishes loading, empty imports and search results', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<MeetingsIndexPage />, {
      initialEntries: ['/meetings'],
    });
    expect(screen.getByText('Loading meetings...')).toBeInTheDocument();
    expect(
      await screen.findByText(/No meeting summaries saved yet/),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Search meetings'), {
      target: { value: 'missing' },
    });
    expect(
      await screen.findByText('No meetings match your search.'),
    ).toBeInTheDocument();
  });

  it('shows a failed import reader separately from an empty list and can retry', async () => {
    mockList.mockRejectedValueOnce(new Error('Storage unavailable'));
    renderWithProviders(<MeetingsIndexPage />, {
      initialEntries: ['/meetings'],
    });

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load meetings: Storage unavailable',
    );
    expect(
      screen.queryByText(/No meeting summaries saved yet/),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Product planning')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('Meetings header sorting', () => {
  it.each([
    ['Title', 'title', 'title_desc'],
    ['Connection', 'connection_asc', 'connection_desc'],
    ['Provider', 'provider_asc', 'provider_desc'],
    ['Meeting date', 'date_asc', 'date_desc'],
    ['Last updated', 'updated_asc', 'updated'],
  ])(
    'toggles %s in both server directions without a sorting menu',
    async (label, ascending, descending) => {
      renderWithProviders(<MeetingsIndexPage />, {
        initialEntries: ['/meetings'],
      });
      await screen.findByText('Product planning');
      const header = screen.getByRole('columnheader', { name: label });
      const button = within(header).getByRole('button');
      expect(
        screen.queryByRole('combobox', { name: 'Sort meetings' }),
      ).not.toBeInTheDocument();
      fireEvent.click(button);
      const first =
        label === 'Meeting date' || label === 'Last updated'
          ? descending
          : ascending;
      const second = first === ascending ? descending : ascending;
      await waitFor(() =>
        expect(mockList).toHaveBeenLastCalledWith(
          expect.objectContaining({ sort: first, offset: 0 }),
        ),
      );
      await waitFor(() =>
        expect(header).toHaveAttribute(
          'aria-sort',
          first === ascending ? 'ascending' : 'descending',
        ),
      );
      fireEvent.click(button);
      await waitFor(() =>
        expect(mockList).toHaveBeenLastCalledWith(
          expect.objectContaining({ sort: second }),
        ),
      );
      await waitFor(() =>
        expect(header).toHaveAttribute(
          'aria-sort',
          second === ascending ? 'ascending' : 'descending',
        ),
      );
    },
  );

  it('keeps focused headers mounted while rejecting stale sort results and clearing busy after errors', async () => {
    let finishAsc!: (value: { items: typeof meetings; total: number }) => void;
    let finishDesc!: (value: { items: typeof meetings; total: number }) => void;
    renderWithProviders(<MeetingsIndexPage />, {
      initialEntries: ['/meetings'],
    });
    await screen.findByText('Product planning');
    mockList
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
    const header = screen.getByRole('columnheader', { name: 'Title' });
    const button = within(header).getByRole('button');
    button.focus();
    fireEvent.click(button);
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true');
    expect(screen.queryByText('Loading meetings...')).not.toBeInTheDocument();
    expect(screen.getByText('Product planning')).toBeVisible();
    expect(document.querySelector('[aria-sort]')).toBeNull();
    expect(button).toHaveFocus();
    fireEvent.click(button);
    await act(async () => {
      finishDesc({
        items: [{ ...meetingFixture, title: 'Current descending' }],
        total: 30,
      });
    });
    await screen.findByText('Current descending');
    await act(async () => {
      finishAsc({
        items: [{ ...meetingFixture, title: 'Stale ascending' }],
        total: 99,
      });
    });
    expect(screen.queryByText('Stale ascending')).not.toBeInTheDocument();
    expect(header).toHaveAttribute('aria-sort', 'descending');
    expect(button).toHaveFocus();
    mockList.mockRejectedValueOnce(new Error('Synthetic read failure'));
    fireEvent.click(button);
    await screen.findByRole('alert');
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'false');
    expect(document.querySelector('[aria-sort]')).toBeNull();
    expect(button).toHaveFocus();
  });

  it('keeps empty feedback outside the horizontally scrollable header columns', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<MeetingsIndexPage />, {
      initialEntries: ['/meetings'],
    });
    const empty = await screen.findByRole('status');
    expect(empty).toHaveTextContent('No meeting summaries saved yet.');
    expect(empty.closest('table')).toBeNull();
    expect(screen.getAllByRole('columnheader')).toHaveLength(5);
    expect(screen.getByRole('button', { name: 'Title' })).toBeEnabled();
    let finish!: (value: { items: typeof meetings; total: number }) => void;
    mockList.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Search meetings' }), {
      target: { value: 'new query' },
    });
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: 'new query' }),
      ),
    );
    expect(
      screen.queryByText(/No meeting summaries saved yet/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText('No meetings match your search.'),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('Loading meetings...')).not.toBeInTheDocument();
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true');
    await act(async () => finish({ items: [], total: 0 }));
    expect(
      await screen.findByText('No meetings match your search.'),
    ).toBeVisible();
  });
});
