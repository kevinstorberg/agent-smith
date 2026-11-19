import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, within } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { ActionItemProposalDetailPage } from '../ActionItemProposalDetailPage';
import { actionItemProposal } from './actionItemProposalFixture';

const mockNavigate = vi.fn();
const mockNotify = vi.fn();

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ id: '1' }),
  };
});

vi.mock('../../context/useNotification', async () => {
  const actual = await vi.importActual<
    typeof import('../../context/useNotification')
  >('../../context/useNotification');
  return {
    ...actual,
    useNotification: () => ({
      notify: mockNotify,
      notifications: [],
      dismiss: vi.fn(),
    }),
  };
});

vi.mock('../../api', () => ({
  api: {
    actionItemProposals: {
      get: vi.fn(),
      approve: vi.fn(),
      reject: vi.fn(),
      remove: vi.fn(),
    },
  },
}));

import { api } from '../../api';

const mockGet = api.actionItemProposals.get as ReturnType<typeof vi.fn>;
const mockApprove = api.actionItemProposals.approve as ReturnType<typeof vi.fn>;
const mockReject = api.actionItemProposals.reject as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  mockGet.mockResolvedValue(actionItemProposal());
  mockApprove.mockImplementation(async () => {
    const result = {
      ...actionItemProposal(),
      status: 'approved',
      applied_ref: { action_item_id: 12 },
    };
    mockGet.mockResolvedValue(result);
    return result;
  });
  mockReject.mockImplementation(async () => {
    const result = { ...actionItemProposal(), status: 'rejected' };
    mockGet.mockResolvedValue(result);
    return result;
  });
});
afterEach(() => vi.useRealTimers());

describe('ActionItemProposalDetailPage', () => {
  it('shows a meeting-backed action item update as reviewed field changes', async () => {
    mockGet.mockResolvedValue(actionItemProposal());
    renderWithProviders(<ActionItemProposalDetailPage />);

    const changes = await screen.findByRole('region', {
      name: 'Proposed action item changes',
    });
    expect(
      within(changes).getByRole('rowheader', { name: 'Deadline' }),
    ).toBeInTheDocument();
    expect(
      within(changes).queryByRole('rowheader', { name: 'Description' }),
    ).not.toBeInTheDocument();
    expect(within(changes).getByText(/November 18, 2026/)).toBeInTheDocument();
    expect(within(changes).getByText(/November 20, 2026/)).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Release planning' }),
    ).toHaveAttribute('href', '/meetings/meeting-123');
    expect(
      screen.getByText(
        'Move the release report deadline to Friday at 5 PM UTC.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
  });

  it('renders a new action item and links to its saved result after approval', async () => {
    const proposal = actionItemProposal({
      action: 'create',
      target_id: null,
      base_version: null,
      before_snapshot: null,
      current_target: null,
    });
    mockGet.mockResolvedValue(proposal);
    const approved = {
      ...proposal,
      status: 'approved',
      applied_ref: { action_item_id: 35 },
    };
    mockApprove.mockImplementation(async () => {
      mockGet.mockResolvedValue(approved);
      return approved;
    });
    renderWithProviders(<ActionItemProposalDetailPage />);

    const content = await screen.findByRole('region', {
      name: 'Proposed action item',
    });
    expect(
      within(content).getByRole('rowheader', { name: 'Title' }),
    ).toBeInTheDocument();
    expect(
      within(content).getByText('Send the release report'),
    ).toBeInTheDocument();
    expect(
      within(content).queryByRole('columnheader', { name: 'Before' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(
      await screen.findByRole('link', { name: 'Open saved action item' }),
    ).toHaveAttribute('href', '/action-items/35');
  });

  it('keeps the reviewed snapshot when the live action item changed', async () => {
    const proposal = actionItemProposal();
    mockGet.mockResolvedValue({
      ...proposal,
      current_target: {
        ...proposal.current_target,
        revision: 4,
        due_at: '2026-12-01T17:00:00Z',
      },
    });
    renderWithProviders(<ActionItemProposalDetailPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This action item changed',
    );
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();
    const changes = screen.getByRole('region', {
      name: 'Proposed action item changes',
    });
    expect(within(changes).getByText(/November 18, 2026/)).toBeInTheDocument();
    expect(
      within(changes).queryByText(/December 1, 2026/),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByText('Current saved action item', { selector: 'summary' }),
    );
    expect(
      within(
        screen.getByRole('region', { name: 'Current saved action item' }),
      ).getByText(/December 1, 2026/),
    ).toBeInTheDocument();
    expect(mockApprove).not.toHaveBeenCalled();
  });

  it.each([{ source_stale: true }, { source_available: false }])(
    'blocks approval after meeting source drift: %j',
    async (flags) => {
      mockGet.mockResolvedValue(actionItemProposal(flags));
      renderWithProviders(<ActionItemProposalDetailPage />);

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'The source meeting changed or is unavailable.',
      );
      expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled();
    },
  );

  it('rejects through the independent Action Item endpoint', async () => {
    renderWithProviders(<ActionItemProposalDetailPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Reject' }));
    await waitFor(() => expect(mockReject).toHaveBeenCalledWith(1));
    expect(
      await screen.findByText('rejected', { exact: true }),
    ).toBeInTheDocument();
    expect(mockApprove).not.toHaveBeenCalled();
  });
});
