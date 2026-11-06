import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../api';
import type { EvalSuite, Paginated } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { EvalSuitesPage } from '../EvalSuitesPage';
import { suiteSortingRows } from './suiteSortingFixture';

vi.mock('../../api', () => ({
  api: { evalConfigs: { suites: { list: vi.fn(), update: vi.fn() } } },
}));
const response = (name: string): Paginated<EvalSuite> => ({
  items: [{ ...suiteSortingRows[0], name }],
  total: 30,
});
const header = (name: string) => screen.getByRole('columnheader', { name });
const button = (name: string) => within(header(name)).getByRole('button');
beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.resetAllMocks();
  vi.mocked(api.evalConfigs.suites.list).mockResolvedValue(
    response('Accepted suite'),
  );
});
describe('Eval Suites header sorting', () => {
  it.each([
    ['Name', 'name', 'name_desc'],
    ['Type', 'type_asc', 'type_desc'],
    ['Scenarios', 'scenario_count_asc', 'scenario_count_desc'],
    ['Enabled', 'enabled_asc', 'enabled_desc'],
    ['Updated', 'updated', 'updated_asc'],
  ])(
    'toggles %s without mutating suite configuration',
    async (label, first, second) => {
      renderWithProviders(<EvalSuitesPage />, {
        initialEntries: ['/eval-configs?sort=newest'],
      });
      await screen.findByText('Accepted suite');
      expect(
        screen.queryByRole('combobox', { name: 'Sort eval suites' }),
      ).not.toBeInTheDocument();
      for (const sort of [first, second]) {
        fireEvent.click(button(label));
        await waitFor(() =>
          expect(api.evalConfigs.suites.list).toHaveBeenLastCalledWith(
            expect.objectContaining({ sort, offset: '0' }),
          ),
        );
        await waitFor(() =>
          expect(header(label)).toHaveAttribute(
            'aria-sort',
            sort.endsWith('_desc') || sort === 'updated'
              ? 'descending'
              : 'ascending',
          ),
        );
      }
      expect(api.evalConfigs.suites.update).not.toHaveBeenCalled();
      expect(
        within(screen.getAllByRole('columnheader').at(-1)!).queryByRole(
          'button',
        ),
      ).toBeNull();
    },
  );
  it('requests global first-page counts from a committed second page while keeping filters', async () => {
    vi.mocked(api.evalConfigs.suites.list).mockImplementation(async (params) =>
      response(
        params?.sort === 'scenario_count_desc'
          ? 'Largest count from outside page'
          : 'Committed page two',
      ),
    );
    renderWithProviders(<EvalSuitesPage />, {
      initialEntries: [
        '/eval-configs?q=release&enabled=false&limit=25&offset=25',
      ],
    });
    await screen.findByText('Committed page two');
    vi.mocked(api.evalConfigs.suites.list).mockClear();
    fireEvent.click(button('Scenarios'));
    await screen.findByText('Committed page two');
    fireEvent.click(button('Scenarios'));
    await screen.findByText('Largest count from outside page');
    expect(api.evalConfigs.suites.list).toHaveBeenLastCalledWith({
      enabled_only: 'false',
      q: 'release',
      enabled: 'false',
      sort: 'scenario_count_desc',
      limit: '25',
      offset: '0',
    });
    expect(screen.getByText('Showing 1–25 of 30')).toBeInTheDocument();
  });
  it('keeps keyboard focus and refuses a stale count result after Desc is accepted', async () => {
    let asc!: (value: Paginated<EvalSuite>) => void;
    let desc!: (value: Paginated<EvalSuite>) => void;
    const a = new Promise<Paginated<EvalSuite>>((r) => {
      asc = r;
    });
    const d = new Promise<Paginated<EvalSuite>>((r) => {
      desc = r;
    });
    vi.mocked(api.evalConfigs.suites.list).mockImplementation((params) =>
      params?.sort === 'scenario_count_asc'
        ? a
        : params?.sort === 'scenario_count_desc'
          ? d
          : Promise.resolve(response('Original suite')),
    );
    renderWithProviders(<EvalSuitesPage />, {
      initialEntries: ['/eval-configs'],
    });
    await screen.findByText('Original suite');
    const target = button('Scenarios');
    target.focus();
    const user = userEvent.setup();
    await user.keyboard('{Enter}');
    await waitFor(() =>
      expect(api.evalConfigs.suites.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'scenario_count_asc' }),
      ),
    );
    expect(target).toHaveFocus();
    expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    expect(screen.getByText('Original suite')).toBeVisible();
    const toggle = screen.getByRole('checkbox', {
      name: 'Enable Original suite',
    });
    expect(toggle).toBeDisabled();
    fireEvent.click(toggle);
    expect(api.evalConfigs.suites.update).not.toHaveBeenCalled();
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true');
    expect(document.querySelector('[aria-sort]')).toBeNull();
    await user.keyboard(' ');
    await act(async () => desc(response('Current count result')));
    await screen.findByText('Current count result');
    await act(async () => asc(response('Stale count result')));
    expect(screen.queryByText('Stale count result')).toBeNull();
    expect(target).toHaveFocus();
    expect(header('Scenarios')).toHaveAttribute('aria-sort', 'descending');
  });
  it('keeps sortable headers for empty results and clears busy on failed ordering', async () => {
    vi.mocked(api.evalConfigs.suites.list).mockResolvedValueOnce({
      items: [],
      total: 0,
    });
    renderWithProviders(<EvalSuitesPage />, {
      initialEntries: ['/eval-configs'],
    });
    await screen.findByText('No eval suites found');
    expect(screen.getByRole('table')).not.toHaveClass('table-empty');
    const target = button('Type');
    target.focus();
    vi.mocked(api.evalConfigs.suites.list).mockRejectedValueOnce(
      new Error('Unavailable'),
    );
    fireEvent.click(target);
    await screen.findByRole('alert');
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'false');
    expect(document.querySelector('[aria-sort]')).toBeNull();
    expect(target).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText('Accepted suite');
    expect(header('Type')).toHaveAttribute('aria-sort', 'ascending');
  });
});
