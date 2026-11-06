import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { AuditIndexPage } from '../AuditIndexPage';

vi.mock('../../api', () => ({
  api: { audit: { list: vi.fn(), counts: vi.fn() } },
}));
import { api } from '../../api';
const event = {
  id: 1,
  correlation_key: 'one',
  agent: 'claude',
  session_id: 'session',
  tool_name: 'Initial row',
  status: 'success',
  created_at: '2026-01-01T12:00:00Z',
  duration_ms: 12,
  project: 'work',
};
const result = (tool: string) => ({
  items: [{ ...event, tool_name: tool }],
  total: 30,
});
beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.clearAllMocks();
  vi.mocked(api.audit.counts).mockResolvedValue({
    claude: 1,
    codex: 0,
    gemini: 0,
  });
  vi.mocked(api.audit.list).mockResolvedValue(result('Initial row') as never);
});

it('removes the sort menu and routes every header pair through current filters at page zero', async () => {
  renderWithProviders(<AuditIndexPage />, {
    initialEntries: [
      '/audit?q=release&agent=claude&status=success&project=work&offset=20&keep=1',
    ],
  });
  await screen.findByText('Initial row');
  expect(
    screen.queryByRole('combobox', { name: 'Sort' }),
  ).not.toBeInTheDocument();
  for (const [label, first, second] of [
    ['Tool', 'tool_asc', 'tool_desc'],
    ['Status', 'status_asc', 'status_desc'],
    ['Agent', 'agent_asc', 'agent_desc'],
    ['Duration', 'duration', 'duration_asc'],
    ['Project', 'project_asc', 'project_desc'],
    ['Time', 'newest', 'oldest'],
  ]) {
    const header = screen.getByRole('columnheader', { name: label });
    fireEvent.click(header.querySelector('button')!);
    await waitFor(() =>
      expect(api.audit.list).toHaveBeenLastCalledWith(
        expect.objectContaining({
          q: 'release',
          agent: 'claude',
          status: 'success',
          project: 'work',
          sort: first,
        }),
        { limit: 10, offset: 0 },
      ),
    );
    fireEvent.click(header.querySelector('button')!);
    await waitFor(() =>
      expect(api.audit.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: second }),
        { limit: 10, offset: 0 },
      ),
    );
  }
});

it('keeps the focused header mounted and rejects stale sort completions', async () => {
  let resolveAsc!: (value: ReturnType<typeof result>) => void;
  let resolveDesc!: (value: ReturnType<typeof result>) => void;
  const asc = new Promise<ReturnType<typeof result>>((resolve) => {
    resolveAsc = resolve;
  });
  const desc = new Promise<ReturnType<typeof result>>((resolve) => {
    resolveDesc = resolve;
  });
  vi.mocked(api.audit.list).mockImplementation(
    (filters) =>
      (filters?.sort === 'tool_asc'
        ? asc
        : filters?.sort === 'tool_desc'
          ? desc
          : Promise.resolve(result('Initial row'))) as never,
  );
  renderWithProviders(<AuditIndexPage />, { initialEntries: ['/audit'] });
  await screen.findByText('Initial row');
  const header = screen.getByRole('columnheader', { name: 'Tool' });
  const button = header.querySelector('button')!;
  button.focus();
  fireEvent.click(button);
  await waitFor(() =>
    expect(api.audit.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort: 'tool_asc' }),
      expect.anything(),
    ),
  );
  expect(button).toHaveFocus();
  expect(header).not.toHaveAttribute('aria-sort');
  fireEvent.click(button);
  await waitFor(() =>
    expect(api.audit.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort: 'tool_desc' }),
      expect.anything(),
    ),
  );
  await act(async () => resolveDesc(result('Accepted descending')));
  expect(await screen.findByText('Accepted descending')).toBeVisible();
  await act(async () => resolveAsc(result('Stale ascending')));
  expect(screen.queryByText('Stale ascending')).not.toBeInTheDocument();
  expect(header).toHaveAttribute('aria-sort', 'descending');
  expect(button).toHaveFocus();
});

it('announces a pending header retry after an error and clears busy when it completes', async () => {
  let resolveRetry!: (value: { items: never[]; total: number }) => void;
  const retry = new Promise<{ items: never[]; total: number }>((resolve) => {
    resolveRetry = resolve;
  });
  vi.mocked(api.audit.list)
    .mockRejectedValueOnce(new Error('Unavailable'))
    .mockReturnValueOnce(retry);
  renderWithProviders(<AuditIndexPage />, { initialEntries: ['/audit'] });
  await screen.findByRole('alert');
  const table = screen.getByRole('table');
  expect(table).toHaveAttribute('aria-busy', 'false');
  const header = screen.getByRole('columnheader', { name: 'Tool' });
  const button = header.querySelector('button')!;
  button.focus();
  fireEvent.click(button);
  await waitFor(() =>
    expect(api.audit.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort: 'tool_asc' }),
      { limit: 10, offset: 0 },
    ),
  );
  expect(table).toHaveAttribute('aria-busy', 'true');
  expect(header).not.toHaveAttribute('aria-sort');
  expect(button).toHaveFocus();
  await act(async () => resolveRetry({ items: [], total: 0 }));
  await screen.findByRole('heading', { name: 'No tool calls yet' });
  expect(table).toHaveAttribute('aria-busy', 'false');
  expect(header).toHaveAttribute('aria-sort', 'ascending');
  expect(button).toHaveFocus();
});
