import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  act,
  screen,
  fireEvent,
  waitFor,
  within,
} from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { ActionItemProposalDetailPage } from '../ActionItemProposalDetailPage';
import { actionItemProposal } from './actionItemProposalFixture';
import { epicGroup } from './actionItemEpicFixture';
import { epicReference } from '../../utils/actionItemEpics';

const mockNavigate = vi.fn();
const mockNotify = vi.fn();
let routeId = '1';

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ id: routeId }),
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
    actionItemEpics: { list: vi.fn() },
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
  routeId = '1';
  vi.mocked(api.actionItemEpics.list).mockResolvedValue({ items: [] });
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
  it('restores focus to the heading when a canonical conflict disables approval', async () => {
    const proposal = actionItemProposal();
    mockGet.mockResolvedValueOnce(proposal).mockResolvedValue({
      ...proposal,
      target_stale: true,
      current_target: { ...proposal.current_target, revision: 4 },
    });
    mockApprove.mockRejectedValueOnce(new Error('Changed during review'));
    renderWithProviders(<ActionItemProposalDetailPage />);
    const approve = await screen.findByRole('button', { name: 'Accept' });
    approve.focus();
    fireEvent.click(approve);
    await screen.findByText(/Changed during review/);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled(),
    );
    expect(approve).toBeDisabled();
    expect(screen.getByRole('heading', { name: proposal.title })).toHaveFocus();
  });

  it('resets the destination on proposal navigation and ignores an earlier in-flight completion', async () => {
    const first = actionItemProposal({
      action: 'create',
      current_parent: null,
      current_target: null,
      base_version: null,
      target_id: null,
    });
    let second = actionItemProposal({
      id: 2,
      title: 'Create: Another task',
      target_name: 'Another task',
      action: 'create',
      current_parent: null,
      current_target: null,
      base_version: null,
      target_id: null,
    });
    const destination = epicGroup(10, []).epic;
    const resolve: ((value: typeof first) => void)[] = [];
    mockGet.mockImplementation(async (id: number) =>
      id === 1 ? first : second,
    );
    mockApprove.mockImplementation(
      () => new Promise((done) => resolve.push(done)),
    );
    vi.mocked(api.actionItemEpics.list).mockResolvedValue({
      items: [destination],
    });
    const view = renderWithProviders(<ActionItemProposalDetailPage />);
    await screen.findByRole('option', { name: destination.title });
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
    routeId = '2';
    view.rerender(<ActionItemProposalDetailPage />);
    await screen.findByRole('heading', { name: second.title });
    expect(screen.getByRole('combobox')).toHaveDisplayValue('No Epic');
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
    expect(mockApprove.mock.calls).toEqual([
      [
        1,
        {
          placement: {
            expected_parent: null,
            destination: epicReference(destination),
          },
        },
      ],
      [2],
    ]);
    const readCount = mockGet.mock.calls.length;
    await act(async () =>
      resolve[0]({
        ...first,
        status: 'approved',
        applied_ref: { action_item_id: 35 },
      }),
    );
    expect(mockGet).toHaveBeenCalledTimes(readCount);
    expect(mockNotify).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
    expect(screen.getByRole('combobox')).toHaveDisplayValue('No Epic');
    second = {
      ...second,
      status: 'approved',
      applied_ref: { action_item_id: 36 },
    };
    await act(async () => resolve[1](second));
    expect(
      await screen.findByRole('link', { name: 'Open saved action item' }),
    ).toHaveAttribute('href', '/action-items/36');
  });

  it('places an accepted create into an Epic and locks decisions through canonical refresh', async () => {
    const proposal = actionItemProposal({
      action: 'create',
      target_id: null,
      base_version: null,
      current_target: null,
      current_parent: null,
    });
    const destination = epicGroup(10, []).epic;
    const approved = {
      ...proposal,
      status: 'approved' as const,
      applied_ref: { action_item_id: 35 },
    };
    let resolveApproval!: (value: typeof approved) => void;
    let resolveRefresh!: (value: typeof approved) => void;
    mockGet.mockResolvedValueOnce(proposal).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRefresh = resolve;
        }),
    );
    mockApprove.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveApproval = resolve;
        }),
    );
    vi.mocked(api.actionItemEpics.list).mockResolvedValue({
      items: [destination],
    });
    renderWithProviders(<ActionItemProposalDetailPage />);
    await screen.findByRole('option', { name: destination.title });
    fireEvent.change(screen.getByRole('combobox', { name: /Epic for/ }), {
      target: { value: '10' },
    });
    const approve = screen.getByRole('button', { name: 'Accept' });
    approve.focus();
    fireEvent.click(approve);
    fireEvent.click(approve);
    expect(mockApprove).toHaveBeenCalledExactlyOnceWith(1, {
      placement: {
        expected_parent: null,
        destination: epicReference(destination),
      },
    });
    await act(async () => resolveApproval(approved));
    await waitFor(() => expect(resolveRefresh).toBeDefined());
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'Delete proposal' }),
    ).toBeDisabled();
    expect(screen.getByRole('combobox')).toBeDisabled();
    await act(async () => resolveRefresh(approved));
    await screen.findByRole('link', { name: 'Open saved action item' });
    expect(screen.getByRole('heading', { name: proposal.title })).toHaveFocus();
    expect(mockApprove).toHaveBeenCalledTimes(1);
  });

  it.each([7, null])(
    'preserves replaced history with replacement reference %s',
    async (replacement) => {
      mockGet.mockResolvedValue(
        actionItemProposal({
          status: 'superseded',
          superseded_by_id: replacement,
        }),
      );
      renderWithProviders(<ActionItemProposalDetailPage />);
      expect(
        await screen.findByText(/Replaced by another Action Item proposal/),
      ).toBeVisible();
      if (replacement === null) {
        expect(screen.getByText(/Replacement unavailable/)).toBeVisible();
        expect(
          screen.queryByRole('link', { name: 'View replacement' }),
        ).not.toBeInTheDocument();
      } else {
        expect(
          screen.getByRole('link', { name: 'View replacement' }),
        ).toHaveAttribute('href', '/action-items/proposals/7');
      }
      expect(
        screen.queryByRole('button', { name: 'Accept' }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Reject' }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('region', { name: 'Proposed action item changes' }),
      ).toHaveTextContent('Deadline');
    },
  );

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
    expect(screen.getByRole('button', { name: 'Accept' })).toBeEnabled();
  });

  it('renders a new action item and links to its saved result after approval', async () => {
    const proposal = actionItemProposal({
      action: 'create',
      target_id: null,
      base_version: null,
      before_snapshot: null,
      current_target: null,
      project: 'Review context',
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
    const { container } = renderWithProviders(<ActionItemProposalDetailPage />);

    const content = await screen.findByRole('region', {
      name: 'Proposed action item',
    });
    expect(container.querySelector('.tag-project')).toHaveTextContent('Work');
    expect(container.querySelector('.tag-project')).not.toHaveTextContent(
      'Review context',
    );
    expect(
      within(content).getByRole('rowheader', { name: 'Title' }),
    ).toBeInTheDocument();
    expect(
      within(content).getByText('Send the release report'),
    ).toBeInTheDocument();
    expect(
      within(content).queryByRole('columnheader', { name: 'Before' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
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
    expect(screen.getByRole('button', { name: 'Accept' })).toBeDisabled();
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
      expect(screen.getByRole('button', { name: 'Accept' })).toBeDisabled();
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
