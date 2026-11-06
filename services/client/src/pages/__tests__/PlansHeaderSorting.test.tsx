import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useLocation } from 'react-router';
import { api } from '../../api';
import type { Paginated, Plan } from '../../api';
import { renderWithProviders } from '../../test-utils';
import {
  defaultView,
  mergeViewCookie,
  readViewCookie,
} from '../../utils/viewPreferences';
import { PlansIndexPage } from '../PlansIndexPage';

vi.mock('../../api', () => ({ api: { plans: { list: vi.fn() } } }));
const plan = (title: string, id = 1) =>
  ({
    id,
    title,
    status: 'draft',
    project: 'work',
    updated_at: '2026-01-15T10:00:00Z',
  }) as Plan;
const response = (title: string, total = 25): Paginated<Plan> => ({
  items: [plan(title)],
  total,
});
function Location() {
  return <output aria-label="URL search">{useLocation().search}</output>;
}
function deferred() {
  let resolve!: (value: Paginated<Plan>) => void;
  const promise = new Promise<Paginated<Plan>>((finish) => {
    resolve = finish;
  });
  return { promise, resolve };
}
const header = (label: string) =>
  screen.getByRole('columnheader', { name: new RegExp(label) });
const button = (label: string) => within(header(label)).getByRole('button');

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.clearAllMocks();
  vi.mocked(api.plans.list).mockResolvedValue(response('Accepted plan', 100));
});

describe('Plans header sorting', () => {
  it.each([
    ['Title', 'title', 'title_desc'],
    ['Status', 'status_asc', 'status_desc'],
    ['Project', 'project_asc', 'project_desc'],
    ['Last Updated', 'updated_asc', 'updated'],
  ])(
    'toggles %s through both server directions without a sort menu',
    async (label, ascending, descending) => {
      renderWithProviders(<PlansIndexPage />, {
        initialEntries: ['/plans?sort=newest'],
      });
      await screen.findByText('Accepted plan');
      expect(
        screen.queryByRole('combobox', { name: 'Sort plans' }),
      ).not.toBeInTheDocument();
      expect(document.querySelector('[aria-sort]')).toBeNull();
      fireEvent.click(button(label));
      const first = label === 'Last Updated' ? descending : ascending;
      const second = label === 'Last Updated' ? ascending : descending;
      await waitFor(() =>
        expect(api.plans.list).toHaveBeenLastCalledWith(
          expect.objectContaining({ sort: first, offset: 0 }),
        ),
      );
      await waitFor(() =>
        expect(header(label)).toHaveAttribute(
          'aria-sort',
          first === ascending ? 'ascending' : 'descending',
        ),
      );
      fireEvent.click(button(label));
      await waitFor(() =>
        expect(api.plans.list).toHaveBeenLastCalledWith(
          expect.objectContaining({ sort: second }),
        ),
      );
      await waitFor(() =>
        expect(header(label)).toHaveAttribute(
          'aria-sort',
          second === ascending ? 'ascending' : 'descending',
        ),
      );
      expect(document.querySelectorAll('[aria-sort]')).toHaveLength(1);
    },
  );

  it('sorts the full server result from a committed second page while preserving filters and page size', async () => {
    vi.mocked(api.plans.list).mockImplementation(async (params) =>
      response(
        params?.sort === 'title'
          ? 'Aardvark outside previous page'
          : params?.offset
            ? 'Committed second page'
            : 'Initial page',
        100,
      ),
    );
    renderWithProviders(
      <>
        <PlansIndexPage />
        <Location />
      </>,
      {
        initialEntries: [
          '/plans?q=release&project=work&status=draft&limit=25&keep=1',
        ],
      },
    );
    await screen.findByText('Initial page');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Committed second page');
    expect(screen.getByText('Showing 26–50 of 100')).toBeInTheDocument();
    vi.mocked(api.plans.list).mockClear();
    fireEvent.click(button('Title'));
    await screen.findByText('Aardvark outside previous page');
    expect(api.plans.list).toHaveBeenCalledExactlyOnceWith({
      limit: 25,
      offset: 0,
      q: 'release',
      project: 'work',
      status: 'draft',
      sort: 'title',
    });
    expect(screen.getByText('Showing 1–25 of 100')).toBeInTheDocument();
    const search = new URLSearchParams(
      screen.getByLabelText('URL search').textContent!,
    );
    expect(search.get('keep')).toBe('1');
    expect(search.get('sort')).toBe('title');
    expect(search.get('offset')).toBe('0');
  });

  it('keeps native keyboard focus while rejecting late Asc after accepted Desc', async () => {
    const ascending = deferred();
    const descending = deferred();
    vi.mocked(api.plans.list).mockImplementation((params) =>
      params?.sort === 'title'
        ? ascending.promise
        : params?.sort === 'title_desc'
          ? descending.promise
          : Promise.resolve(response('Original accepted row')),
    );
    renderWithProviders(<PlansIndexPage />, { initialEntries: ['/plans'] });
    await screen.findByText('Original accepted row');
    const user = userEvent.setup();
    const titleButton = button('Title');
    let tabs = 0;
    while (document.activeElement !== titleButton && tabs++ < 20)
      await user.tab();
    expect(titleButton).toHaveFocus();
    await user.keyboard('{Enter}');
    await waitFor(() =>
      expect(api.plans.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'title' }),
      ),
    );
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true');
    expect(document.querySelector('[aria-sort]')).toBeNull();
    expect(titleButton).toHaveFocus();
    expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    expect(screen.getByText('Original accepted row')).toBeVisible();
    expect(titleButton).toBeEnabled();
    await user.keyboard(' ');
    await waitFor(() =>
      expect(api.plans.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'title_desc' }),
      ),
    );
    await act(async () =>
      descending.resolve(response('Newest Desc result', 40)),
    );
    await screen.findByText('Newest Desc result');
    expect(header('Title')).toHaveAttribute('aria-sort', 'descending');
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'false');
    await act(async () => ascending.resolve(response('Stale Asc result', 99)));
    expect(screen.queryByText('Stale Asc result')).not.toBeInTheDocument();
    expect(screen.getByText('Newest Desc result')).toBeInTheDocument();
    expect(screen.getByText('Showing 1–10 of 40')).toBeInTheDocument();
    expect(titleButton).toHaveFocus();
    expect(
      readViewCookie(document.cookie).find((entry) => entry.key === 'plans')
        ?.values.sort,
    ).toBe('title_desc');
  });

  it('clears busy after a failed new order and accepts that order only after retry', async () => {
    renderWithProviders(<PlansIndexPage />, { initialEntries: ['/plans'] });
    await screen.findByText('Accepted plan');
    const titleButton = button('Title');
    titleButton.focus();
    vi.mocked(api.plans.list).mockRejectedValueOnce(
      new Error('Ordering unavailable'),
    );
    fireEvent.click(titleButton);
    await screen.findByRole('alert');
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'false');
    expect(document.querySelector('[aria-sort]')).toBeNull();
    expect(titleButton).toBeEnabled();
    expect(titleButton).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText('Accepted plan');
    expect(header('Title')).toHaveAttribute('aria-sort', 'ascending');
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'false');
    expect(api.plans.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort: 'title', offset: 0 }),
    );
  });

  it('restores every new direction and legacy aliases on the first request after remount', async () => {
    for (const sort of [
      'title',
      'title_desc',
      'status_asc',
      'status_desc',
      'project_asc',
      'project_desc',
      'updated',
      'updated_asc',
      'newest',
    ] as const) {
      document.cookie = mergeViewCookie('', 'plans', {
        ...defaultView('plans'),
        sort,
        limit: 25,
        offset: 25,
      });
      vi.mocked(api.plans.list).mockClear();
      const rendered = renderWithProviders(<PlansIndexPage />, {
        initialEntries: ['/plans'],
      });
      await screen.findByText('Accepted plan');
      expect(api.plans.list).toHaveBeenCalledExactlyOnceWith(
        expect.objectContaining({ sort, limit: 25, offset: 25 }),
      );
      rendered.unmount();
    }
  });
});
