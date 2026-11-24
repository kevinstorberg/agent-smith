import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { ActionItemProposalsIndexPage } from '../ActionItemProposalsIndexPage';
import { actionItemProposal } from './actionItemProposalFixture';
import { api } from '../../api';
import type { ActionItemProposal } from '../../api';

vi.mock('../../api', () => ({
  api: {
    actionItemProposals: {
      list: vi.fn(),
      counts: vi.fn(),
      approve: vi.fn(),
      reject: vi.fn(),
    },
  },
}));

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.resetAllMocks();
  vi.mocked(api.actionItemProposals.list).mockResolvedValue({
    items: [actionItemProposal()],
    total: 1,
  });
  vi.mocked(api.actionItemProposals.counts).mockResolvedValue({
    pending: 1,
    approved: 0,
    rejected: 0,
    superseded: 0,
  });
  vi.mocked(api.actionItemProposals.approve).mockResolvedValue(
    actionItemProposal({ status: 'approved' }),
  );
  vi.mocked(api.actionItemProposals.reject).mockResolvedValue(
    actionItemProposal({ status: 'rejected' }),
  );
});

function render() {
  return renderWithProviders(<ActionItemProposalsIndexPage />, {
    initialEntries: ['/action-items/proposals'],
  });
}

describe('Proposed Action Items', () => {
  it('shows read-only replaced history with its own status preference and replacement link', async () => {
    vi.mocked(api.actionItemProposals.list).mockResolvedValue({
      items: [
        actionItemProposal({ status: 'superseded', superseded_by_id: 7 }),
      ],
      total: 1,
    });
    vi.mocked(api.actionItemProposals.counts).mockResolvedValue({
      pending: 0,
      approved: 0,
      rejected: 0,
      superseded: 1,
    });
    renderWithProviders(<ActionItemProposalsIndexPage />, {
      initialEntries: ['/action-items/proposals?status=superseded'],
    });
    expect(
      await screen.findByRole('link', { name: 'View replacement' }),
    ).toHaveAttribute('href', '/action-items/proposals/7');
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveValue(
      'superseded',
    );
    expect(
      screen.getByRole('option', { name: 'Superseded (1)' }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Accept' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Reject' }),
    ).not.toBeInTheDocument();
    expect(api.actionItemProposals.list).toHaveBeenCalledWith(
      'superseded',
      expect.anything(),
    );
  });

  it('keeps proposed deadlines and nondefault create status visible beside one title', async () => {
    const proposal = actionItemProposal({
      action: 'create',
      target_id: null,
      base_version: null,
      before_snapshot: null,
      current_target: null,
      proposed_item: {
        title: 'Send the release report',
        description: 'Complete supporting context',
        due_at: '2026-11-25T17:00:00Z',
        status: 'completed',
        project: 'Work',
      },
    });
    vi.mocked(api.actionItemProposals.list).mockResolvedValue({
      items: [proposal],
      total: 1,
    });
    const { container } = render();
    expect(await screen.findByText('Creates completed item')).toBeVisible();
    expect(screen.getByText(/^Due/)).toHaveTextContent('November 25, 2026');
    expect(screen.getByText('Complete supporting context')).not.toBeVisible();
    expect(container.querySelector('details')).not.toHaveAttribute('open');
    expect(
      screen.getAllByRole('link', { name: proposal.target_name }),
    ).toHaveLength(1);
    expect(
      screen.queryByRole('link', { name: 'Review new Action Item' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Details & evidence'));
    expect(screen.getByText('Complete supporting context')).toBeVisible();
    expect(
      screen.queryByRole('rowheader', { name: 'Title' }),
    ).not.toBeInTheDocument();
  });

  it('omits an empty create table without changing the detail navigation', async () => {
    vi.mocked(api.actionItemProposals.list).mockResolvedValue({
      items: [
        actionItemProposal({
          action: 'create',
          target_id: null,
          base_version: null,
          before_snapshot: null,
          current_target: null,
          proposed_item: { title: 'Send the release report', status: 'open' },
        }),
      ],
      total: 1,
    });
    render();
    expect(
      await screen.findByRole('link', { name: 'Send the release report' }),
    ).toHaveAttribute('href', '/action-items/proposals/1');
    fireEvent.click(screen.getByText('Details & evidence'));
    expect(
      screen.queryByRole('region', {
        name: 'Proposed action item',
      }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept' })).toBeEnabled();
  });

  it('keeps a proposed title change visible before expanding supporting context', async () => {
    const proposal = actionItemProposal();
    vi.mocked(api.actionItemProposals.list).mockResolvedValue({
      items: [
        {
          ...proposal,
          proposed_item: {
            ...proposal.proposed_item,
            title: 'Send the revised release report',
          },
        },
      ],
      total: 1,
    });
    render();
    const changes = await screen.findByRole('region', {
      name: 'Proposed action item changes',
    });
    expect(changes).toHaveTextContent('Send the release report');
    expect(changes).toHaveTextContent('Send the revised release report');
    expect(screen.getByRole('rowheader', { name: 'Title' })).toBeVisible();
  });

  it('preserves query preferences when the status select changes', async () => {
    renderWithProviders(<ActionItemProposalsIndexPage />, {
      initialEntries: ['/action-items/proposals?status=approved&q=release'],
    });
    await waitFor(() =>
      expect(api.actionItemProposals.list).toHaveBeenCalledWith(
        'approved',
        expect.objectContaining({ q: 'release' }),
      ),
    );
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveValue(
      'approved',
    );
    fireEvent.change(screen.getByRole('combobox', { name: 'Status' }), {
      target: { value: '' },
    });
    await waitFor(() =>
      expect(api.actionItemProposals.list).toHaveBeenLastCalledWith(
        undefined,
        expect.objectContaining({ q: 'release' }),
      ),
    );
    expect(
      screen.getByPlaceholderText('Search proposed action items...'),
    ).toHaveValue('release');
  });

  it('does not refresh another view after a pending decision unmounts', async () => {
    let resolve!: (value: ActionItemProposal) => void;
    vi.mocked(api.actionItemProposals.approve).mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const view = render();
    fireEvent.click(await screen.findByRole('button', { name: 'Accept' }));
    view.unmount();
    await act(async () => resolve(actionItemProposal({ status: 'approved' })));
    expect(api.actionItemProposals.approve).toHaveBeenCalledExactlyOnceWith(1);
    expect(api.actionItemProposals.list).toHaveBeenCalledTimes(1);
    expect(api.actionItemProposals.counts).toHaveBeenCalledTimes(1);
  });

  it('shows the actual proposed changes and their evidence in the list', async () => {
    render();
    expect(
      await screen.findByRole('region', {
        name: 'Proposed action item changes',
      }),
    ).toHaveTextContent('Deadline');
    expect(screen.getByText(/November 18, 2026/)).toBeInTheDocument();
    expect(screen.getByText(/November 20, 2026/)).toBeInTheDocument();
    const evidence = screen.getByText(
      'Move the release report deadline to Friday at 5 PM UTC.',
    );
    expect(evidence).not.toBeVisible();
    fireEvent.click(screen.getByText('Details & evidence'));
    expect(evidence).toBeVisible();
  });

  it.each(['approve', 'reject'] as const)(
    'can %s directly and refresh the list and counts',
    async (action) => {
      render();
      const button = await screen.findByRole('button', {
        name: action === 'approve' ? 'Accept' : 'Reject',
      });
      vi.mocked(api.actionItemProposals.list).mockResolvedValue({
        items: [],
        total: 0,
      });
      fireEvent.click(button);
      await waitFor(() =>
        expect(api.actionItemProposals[action]).toHaveBeenCalledExactlyOnceWith(
          1,
        ),
      );
      expect(
        await screen.findByText('No pending proposed Action Items'),
      ).toBeInTheDocument();
      expect(api.actionItemProposals.counts).toHaveBeenCalledTimes(2);
    },
  );

  it.each([
    { source_stale: true },
    { source_available: false },
    { target_stale: true },
  ])('blocks stale acceptance but permits rejection: %j', async (flags) => {
    vi.mocked(api.actionItemProposals.list).mockResolvedValue({
      items: [actionItemProposal(flags)],
      total: 1,
    });
    render();
    expect(
      await screen.findByRole('button', { name: 'Accept' }),
    ).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled();
  });

  it.each(['approved', 'rejected'] as const)(
    'has no decision controls on %s records',
    async (status) => {
      vi.mocked(api.actionItemProposals.list).mockResolvedValue({
        items: [actionItemProposal({ status })],
        total: 1,
      });
      render();
      await screen.findByRole('link', { name: 'Send the release report' });
      expect(
        screen.queryByRole('button', { name: 'Accept' }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Reject' }),
      ).not.toBeInTheDocument();
    },
  );

  it('allows only one decision until the response and refresh finish', async () => {
    let resolve!: (value: ActionItemProposal) => void;
    vi.mocked(api.actionItemProposals.approve).mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    render();
    const accept = await screen.findByRole('button', {
      name: 'Accept',
    });
    const reject = screen.getByRole('button', { name: 'Reject' });
    fireEvent.click(accept);
    fireEvent.click(accept);
    fireEvent.click(reject);
    expect(api.actionItemProposals.approve).toHaveBeenCalledTimes(1);
    expect(api.actionItemProposals.reject).not.toHaveBeenCalled();
    expect(reject).toBeDisabled();
    vi.mocked(api.actionItemProposals.list).mockResolvedValue({
      items: [],
      total: 0,
    });
    await act(async () => resolve(actionItemProposal({ status: 'approved' })));
    expect(
      await screen.findByText('No pending proposed Action Items'),
    ).toBeInTheDocument();
  });

  it('refreshes the current filter when it changes during a decision', async () => {
    let resolve!: (value: ActionItemProposal) => void;
    vi.mocked(api.actionItemProposals.approve).mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    render();
    fireEvent.click(await screen.findByRole('button', { name: 'Accept' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Status' }), {
      target: { value: 'approved' },
    });
    await waitFor(() =>
      expect(api.actionItemProposals.list).toHaveBeenLastCalledWith(
        'approved',
        expect.any(Object),
      ),
    );
    await act(async () => resolve(actionItemProposal({ status: 'approved' })));
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Status' })).toHaveValue(
        'approved',
      ),
    );
    expect(api.actionItemProposals.list).toHaveBeenLastCalledWith(
      'approved',
      expect.any(Object),
    );
  });

  it('retains unresolved proposals after a decision conflict and releases the lock', async () => {
    vi.mocked(api.actionItemProposals.approve).mockRejectedValue(
      new Error('Source changed'),
    );
    render();
    fireEvent.click(await screen.findByRole('button', { name: 'Accept' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Source changed',
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled(),
    );
    expect(
      screen.getByRole('link', { name: 'Send the release report' }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    await waitFor(() =>
      expect(api.actionItemProposals.reject).toHaveBeenCalledExactlyOnceWith(1),
    );
  });

  it('can retry a failed refresh after a successful decision', async () => {
    render();
    const accept = await screen.findByRole('button', {
      name: 'Accept',
    });
    vi.mocked(api.actionItemProposals.list).mockRejectedValueOnce(
      new Error('Read failed'),
    );
    fireEvent.click(accept);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load proposed Action Items',
    );
    vi.mocked(api.actionItemProposals.list).mockResolvedValue({
      items: [],
      total: 0,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(
      await screen.findByText('No pending proposed Action Items'),
    ).toBeInTheDocument();
    expect(api.actionItemProposals.approve).toHaveBeenCalledTimes(1);
  });

  it('returns to the preceding page after deciding the last item', async () => {
    let decided = false;
    vi.mocked(api.actionItemProposals.list).mockImplementation(
      async (_status, options) => ({
        items:
          options?.offset === 10
            ? decided
              ? []
              : [actionItemProposal({ id: 11 })]
            : [actionItemProposal()],
        total: decided ? 10 : 11,
      }),
    );
    vi.mocked(api.actionItemProposals.reject).mockImplementation(async () => {
      decided = true;
      return actionItemProposal({ id: 11, status: 'rejected' });
    });
    render();
    fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
    await waitFor(() =>
      expect(api.actionItemProposals.list).toHaveBeenLastCalledWith(
        'pending',
        expect.objectContaining({ offset: 10 }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    await waitFor(() =>
      expect(api.actionItemProposals.list).toHaveBeenLastCalledWith(
        'pending',
        expect.objectContaining({ offset: 0 }),
      ),
    );
    expect(await screen.findByRole('button', { name: 'Accept' })).toBeEnabled();
    expect(api.actionItemProposals.reject).toHaveBeenCalledExactlyOnceWith(11);
  });
  it('loads its own records and links to its own review page', async () => {
    render();
    expect(
      await screen.findByRole('link', { name: 'Send the release report' }),
    ).toHaveAttribute('href', '/action-items/proposals/1');
    expect(
      screen.getByRole('heading', { name: 'Proposed Action Items' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Update')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Generate now' }),
    ).not.toBeInTheDocument();
    expect(api.actionItemProposals.list).toHaveBeenCalledWith(
      'pending',
      expect.objectContaining({ limit: 10, offset: 0 }),
    );
  });

  it('shows new Action Item suggestions separately from saved items', async () => {
    vi.mocked(api.actionItemProposals.list).mockResolvedValue({
      items: [
        actionItemProposal({
          action: 'create',
          target_id: null,
          base_version: null,
        }),
      ],
      total: 1,
    });
    render();
    expect(await screen.findByText('New')).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Saved action items' }),
    ).toHaveAttribute('href', '/action-items');
  });

  it('uses independent status preferences and counts', async () => {
    render();
    fireEvent.change(await screen.findByRole('combobox', { name: 'Status' }), {
      target: { value: 'approved' },
    });
    await waitFor(() =>
      expect(api.actionItemProposals.list).toHaveBeenLastCalledWith(
        'approved',
        expect.any(Object),
      ),
    );
  });

  it('searches its own records', async () => {
    render();
    fireEvent.change(
      screen.getByPlaceholderText('Search proposed action items...'),
      { target: { value: 'release' } },
    );
    await waitFor(() =>
      expect(api.actionItemProposals.list).toHaveBeenLastCalledWith(
        'pending',
        expect.objectContaining({ q: 'release' }),
      ),
    );
  });

  it('explains the empty queue without offering harness generation', async () => {
    vi.mocked(api.actionItemProposals.list).mockResolvedValue({
      items: [],
      total: 0,
    });
    render();
    expect(
      await screen.findByText('No pending proposed Action Items'),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open meetings' })).toHaveAttribute(
      'href',
      '/meetings',
    );
    expect(
      screen.queryByRole('button', { name: 'Generate now' }),
    ).not.toBeInTheDocument();
  });

  it('shows a retryable failure without showing an empty queue', async () => {
    vi.mocked(api.actionItemProposals.list).mockRejectedValue(
      new Error('Fixture failure'),
    );
    render();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load proposed Action Items',
    );
    expect(
      screen.queryByText('No pending proposed Action Items'),
    ).not.toBeInTheDocument();
  });
});
