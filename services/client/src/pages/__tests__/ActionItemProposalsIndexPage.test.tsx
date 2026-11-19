import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { ActionItemProposalsIndexPage } from '../ActionItemProposalsIndexPage';
import { actionItemProposal } from './actionItemProposalFixture';
import { api } from '../../api';

vi.mock('../../api', () => ({
  api: { actionItemProposals: { list: vi.fn(), counts: vi.fn() } },
}));

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.clearAllMocks();
  vi.mocked(api.actionItemProposals.list).mockResolvedValue({
    items: [actionItemProposal()],
    total: 1,
  });
  vi.mocked(api.actionItemProposals.counts).mockResolvedValue({
    pending: 1,
    approved: 0,
    rejected: 0,
  });
});

function render() {
  return renderWithProviders(<ActionItemProposalsIndexPage />, {
    initialEntries: ['/action-items/proposals'],
  });
}

describe('Proposed Action Items', () => {
  it('loads its own records and links to its own review page', async () => {
    render();
    expect(
      await screen.findByRole('link', { name: 'Send the release report' }),
    ).toHaveAttribute('href', '/action-items/proposals/1');
    expect(
      screen.getByRole('heading', { name: 'Proposed Action Items' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Suggested update')).toBeInTheDocument();
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
    expect(await screen.findByText('New Action Item')).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Saved action items' }),
    ).toHaveAttribute('href', '/action-items');
  });

  it('uses independent status preferences and counts', async () => {
    render();
    fireEvent.click(
      await screen.findByRole('button', { name: 'approved (0)' }),
    );
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
