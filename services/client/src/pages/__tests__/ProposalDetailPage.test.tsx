import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { ProposalDetailPage } from '../ProposalDetailPage';

const mockNavigate = vi.fn();
const mockNotify = vi.fn();

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useNavigate: () => mockNavigate, useParams: () => ({ id: '1' }) };
});

vi.mock('../../context/useNotification', async () => {
  const actual = await vi.importActual<typeof import('../../context/useNotification')>('../../context/useNotification');
  return {
    ...actual,
    useNotification: () => ({ notify: mockNotify, notifications: [], dismiss: vi.fn() }),
  };
});

vi.mock('../../api', () => ({
  api: {
    proposals: {
      get: vi.fn(),
      approve: vi.fn(),
      reject: vi.fn(),
      remove: vi.fn(),
    },
  },
}));

import { api } from '../../api';

const mockGet = api.proposals.get as ReturnType<typeof vi.fn>;
const mockApprove = api.proposals.approve as ReturnType<typeof vi.fn>;
const mockReject = api.proposals.reject as ReturnType<typeof vi.fn>;

const ruleUpdateProposal = {
  id: 1,
  target_kind: 'rule',
  action: 'update',
  proposed_item_id: 42,
  target_name: 'dry',
  project: null,
  target_id: 40,
  base_version: 3,
  title: 'Clarify the DRY rule',
  rationale: 'Recent plans show step 1 is misread.',
  evidence: [
    { source: 'plan', id: '12', note: 'misapplication report' },
    { source: 'memory', id: 'abc', note: '' },
  ],
  status: 'pending',
  applied_ref: null,
  created_at: '2026-06-01T10:00:00Z',
  updated_at: '2026-06-01T10:00:00Z',
  proposed_item: { content: { body: '## DRY rule, clarified', metadata: {} } },
  current_target: { content: { body: '## DRY rule', metadata: {} }, version: 3 },
};

beforeEach(() => {
  vi.clearAllMocks();
  mockGet.mockResolvedValue(ruleUpdateProposal);
  mockApprove.mockResolvedValue({ ...ruleUpdateProposal, status: 'approved' });
  mockReject.mockResolvedValue({ ...ruleUpdateProposal, status: 'rejected' });
});

describe('ProposalDetailPage', () => {
  it('renders rationale, evidence links, and a two-pane diff for updates', async () => {
    renderWithProviders(<ProposalDetailPage />);

    expect(await screen.findByText('Clarify the DRY rule')).toBeInTheDocument();
    expect(screen.getByText(/step 1 is misread/)).toBeInTheDocument();
    expect(screen.getByText('plan 12').closest('a')).toHaveAttribute('href', '/plans/12');
    expect(screen.getByText('memory abc')).toBeInTheDocument();
    expect(screen.getByText('Current')).toBeInTheDocument();
    expect(screen.getByText('Proposed')).toBeInTheDocument();
    expect(screen.getByText('## DRY rule')).toBeInTheDocument();
    expect(screen.getByText('## DRY rule, clarified')).toBeInTheDocument();
  });

  it('approves and reflects the new status', async () => {
    renderWithProviders(<ProposalDetailPage />);

    fireEvent.click(await screen.findByText('Approve'));

    await waitFor(() => expect(mockApprove).toHaveBeenCalledWith(1));
    expect(await screen.findByText('approved')).toBeInTheDocument();
    expect(screen.queryByText('Approve')).not.toBeInTheDocument();
  });

  it('rejects and reflects the new status', async () => {
    renderWithProviders(<ProposalDetailPage />);

    fireEvent.click(await screen.findByText('Reject'));

    await waitFor(() => expect(mockReject).toHaveBeenCalledWith(1));
    expect(await screen.findByText('rejected')).toBeInTheDocument();
  });

  it('surfaces approve conflicts and reloads', async () => {
    mockApprove.mockRejectedValue(new Error('rule changed (v3 -> v4) after this proposal was filed'));
    renderWithProviders(<ProposalDetailPage />);

    fireEvent.click(await screen.findByText('Approve'));

    await waitFor(() =>
      expect(mockNotify).toHaveBeenCalledWith(expect.stringMatching(/approve failed: rule changed/), 'error'),
    );
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it('disables approve and warns when the target was deleted', async () => {
    mockGet.mockResolvedValue({ ...ruleUpdateProposal, current_target: null });
    renderWithProviders(<ProposalDetailPage />);

    expect(await screen.findByText(/was deleted/)).toBeInTheDocument();
    expect(screen.getByText('Approve')).toBeDisabled();
  });

  it('shows a single proposed pane plus job JSON for job creates', async () => {
    mockGet.mockResolvedValue({
      ...ruleUpdateProposal,
      target_kind: 'job',
      action: 'create',
      target_name: 'nightly-cleanup',
      current_target: null,
      proposed_item: {
        schedule_config: { days: 1 },
        input_params: { command: 'echo cleanup' },
        description: 'proposed',
      },
    });
    renderWithProviders(<ProposalDetailPage />);

    expect(await screen.findByText('Proposed content')).toBeInTheDocument();
    expect(screen.queryByText('Current')).not.toBeInTheDocument();
    expect(screen.getByText(/echo cleanup/)).toBeInTheDocument();
  });
});
