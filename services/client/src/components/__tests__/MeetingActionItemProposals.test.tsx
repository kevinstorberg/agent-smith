import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { MeetingActionItemProposals } from '../MeetingActionItemProposals';
import type { MeetingActionItemProposals as ProposalState } from '../../api';

vi.mock('../../api', () => ({
  api: { meetings: { requestActionItemProposals: vi.fn() } },
}));

import { api } from '../../api';

const request = vi.mocked(api.meetings.requestActionItemProposals);
const changed = vi.fn();
const state: ProposalState = {
  status: 'not_queued',
  error_type: null,
  proposal_count: 0,
  attempts: 0,
  next_attempt_at: null,
  worker_available: true,
};
const render = (value: ProposalState | null = state) =>
  renderWithProviders(
    <MeetingActionItemProposals
      meetingId="meeting-123"
      revision={7}
      state={value}
      onChanged={changed}
    />,
  );

beforeEach(() => {
  vi.clearAllMocks();
  request.mockResolvedValue({ ...state, status: 'pending' });
});

describe('MeetingActionItemProposals', () => {
  it.each(['pending', 'failed'] as const)(
    'explains incomplete matching capacity while %s',
    (status) => {
      render({ ...state, status, error_type: 'ActionItemContextTooLarge' });
      expect(screen.getByRole('status')).toHaveTextContent(
        'too large to compare completely; no partial matching was performed.',
      );
    },
  );

  it('queues explicit historical analysis using the reviewed meeting revision', async () => {
    render();
    fireEvent.click(
      screen.getByRole('button', { name: 'Propose action items' }),
    );
    await waitFor(() => expect(request).toHaveBeenCalledWith('meeting-123', 7));
    expect(changed).toHaveBeenCalledOnce();
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Action items stay unchanged until you approve.',
    );
    expect(
      screen.getByRole('link', { name: 'Review proposed action items' }),
    ).toHaveAttribute('href', '/action-items/proposals?status=pending');
  });

  it.each(['pending', 'running'] as const)(
    'prevents duplicate requests while %s',
    (status) => {
      render({ ...state, status });
      expect(
        screen.getByRole('button', { name: 'Generating proposals…' }),
      ).toBeDisabled();
      expect(request).not.toHaveBeenCalled();
    },
  );

  it('disables generation until status loads and when no worker is available', () => {
    const view = render(null);
    expect(
      screen.getByRole('button', { name: 'Propose action items' }),
    ).toBeDisabled();
    view.unmount();
    render({ ...state, worker_available: false });
    expect(
      screen.getByRole('button', { name: 'Propose action items' }),
    ).toBeDisabled();
    expect(
      screen.getByText(/Enable a meeting ingestion job/),
    ).toBeInTheDocument();
  });

  it('shows omissions when analysis finishes with no proposals', () => {
    render({
      ...state,
      status: 'done',
      reason: 'The matching task was ambiguous.',
    });
    expect(
      screen.getByText('Complete · 0 proposals saved'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('The matching task was ambiguous.'),
    ).toBeInTheDocument();
  });

  it('offers retry and reports source or job conflicts without task changes', async () => {
    request.mockRejectedValue(
      new Error('Meeting changed. Refresh before generating proposals.'),
    );
    render({
      ...state,
      status: 'failed',
      error_type: 'ActionItemAnalysisError',
    });
    fireEvent.click(
      screen.getByRole('button', { name: 'Retry Action Item proposals' }),
    );
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Meeting changed. Refresh before generating proposals.',
    );
    expect(changed).not.toHaveBeenCalled();
  });
});
