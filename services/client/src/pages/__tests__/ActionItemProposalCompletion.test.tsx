import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router';
import { api, ApiError, type ActionItemProposal } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { ActionItemProposalsIndexPage } from '../ActionItemProposalsIndexPage';
import { ActionItemProposalDetailPage } from '../ActionItemProposalDetailPage';
import { actionItemProposal } from './actionItemProposalFixture';
import { epicGroup } from './actionItemEpicFixture';
import { deferred } from './actionItemFixture';
import { epicReference } from '../../utils/actionItemEpics';
import { chooseEpic } from '../../test-utils/epicPicker';

vi.mock('../../api', async (original) => {
  const actual = await original<typeof import('../../api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      actionItemEpics: { list: vi.fn() },
      actionItemProposals: {
        list: vi.fn(),
        counts: vi.fn(),
        get: vi.fn(),
        approve: vi.fn(),
        reject: vi.fn(),
        remove: vi.fn(),
      },
    },
  };
});

let proposal: ActionItemProposal;
const destination = epicGroup(10, []).epic;
const parent = epicReference(epicGroup(20, []).epic);
const placement = {
  expected_parent: parent,
  destination: epicReference(destination),
};
function completed(): ActionItemProposal {
  return {
    ...proposal,
    status: 'approved',
    review_outcome: 'completed',
    applied_ref: { action_item_id: 12, review_outcome: 'completed', placement },
  };
}
function renderPage(view: 'list' | 'detail', history = false) {
  return renderWithProviders(
    <Routes>
      <Route
        path="/action-items/proposals"
        element={<ActionItemProposalsIndexPage />}
      />
      <Route
        path="/action-items/proposals/:id"
        element={<ActionItemProposalDetailPage />}
      />
    </Routes>,
    {
      initialEntries: [
        view === 'detail'
          ? '/action-items/proposals/1'
          : `/action-items/proposals${history ? '?status=approved' : ''}`,
      ],
    },
  );
}
const done = () =>
  screen.getByRole('button', { name: `Complete ${proposal.target_name}` });

beforeEach(() => {
  vi.restoreAllMocks();
  vi.resetAllMocks();
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  proposal = actionItemProposal({
    current_parent: parent,
    current_parent_title: 'Original Epic',
  });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  vi.mocked(api.actionItemEpics.list).mockResolvedValue({
    items: [destination],
  });
  vi.mocked(api.actionItemProposals.get).mockImplementation(
    async () => proposal,
  );
  vi.mocked(api.actionItemProposals.list).mockImplementation(async (status) => {
    const items = !status || status === proposal.status ? [proposal] : [];
    return { items, total: items.length };
  });
  vi.mocked(api.actionItemProposals.counts).mockImplementation(async () => ({
    pending: proposal.status === 'pending' ? 1 : 0,
    approved: proposal.status === 'approved' ? 1 : 0,
    rejected: proposal.status === 'rejected' ? 1 : 0,
    superseded: 0,
  }));
  vi.mocked(api.actionItemProposals.approve).mockImplementation(async () => {
    proposal = completed();
    return proposal;
  });
});

for (const view of ['list', 'detail'] as const) {
  describe(`${view} proposal completion`, () => {
    it('cancels without an API decision and accepts exactly once with complete:true and reviewed placement', async () => {
      renderPage(view);
      const select = await screen.findByRole('button', { name: /Epic for/ });
      await waitFor(() => expect(select).toBeEnabled());
      chooseEpic(select, '10');
      vi.mocked(window.confirm).mockReturnValueOnce(false);
      fireEvent.click(done());
      expect(api.actionItemProposals.approve).not.toHaveBeenCalled();
      fireEvent.click(done());
      await waitFor(() =>
        expect(api.actionItemProposals.approve).toHaveBeenCalledExactlyOnceWith(
          1,
          { complete: true, placement },
        ),
      );
      expect(api.actionItemProposals.reject).not.toHaveBeenCalled();
      await waitFor(() =>
        expect(
          screen.queryByRole('button', {
            name: `Complete ${proposal.target_name}`,
          }),
        ).not.toBeInTheDocument(),
      );
      expect(window.confirm).toHaveBeenCalledTimes(2);
    });

    it.each([409, 504])(
      'retains the same completion and placement intent on an explicit retry after%s',
      async (status) => {
        vi.mocked(api.actionItemProposals.approve).mockRejectedValueOnce(
          new ApiError('Completion was not confirmed', status),
        );
        renderPage(view);
        const select = await screen.findByRole('button', { name: /Epic for/ });
        chooseEpic(select, '10');
        fireEvent.click(done());
        await screen.findByText(/Completion was not confirmed/);
        await waitFor(() => expect(done()).toBeEnabled());
        expect(api.actionItemProposals.approve).toHaveBeenCalledTimes(1);
        expect(
          screen.queryByText('accepted as done', { exact: true }),
        ).not.toBeInTheDocument();
        fireEvent.click(done());
        await waitFor(() =>
          expect(api.actionItemProposals.approve).toHaveBeenCalledTimes(2),
        );
        expect(vi.mocked(api.actionItemProposals.approve).mock.calls).toEqual([
          [1, { complete: true, placement }],
          [1, { complete: true, placement }],
        ]);
      },
    );

    it('disables Done when canonical review reveals a changed source', async () => {
      proposal = { ...proposal, source_stale: true };
      renderPage(view);
      await screen.findByRole('button', {
        name: `Complete ${proposal.target_name}`,
      });
      expect(done()).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Accept' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled();
      fireEvent.click(done());
      expect(api.actionItemProposals.approve).not.toHaveBeenCalled();
      expect(window.confirm).not.toHaveBeenCalled();
    });

    it('uses canonical completion history after the server applied Done but its response was lost', async () => {
      vi.mocked(api.actionItemProposals.approve).mockImplementationOnce(
        async () => {
          proposal = {
            ...completed(),
            current_target: {
              ...proposal.current_target,
              status: 'open',
              revision: 99,
            },
          };
          throw new ApiError('Completion response was lost', 504);
        },
      );
      renderPage(view);
      await screen.findByRole('button', {
        name: `Complete ${proposal.target_name}`,
      });
      fireEvent.click(done());
      await screen.findByText(/Completion response was lost/);
      await waitFor(() =>
        expect(
          screen.queryByRole('button', {
            name: `Complete ${proposal.target_name}`,
          }),
        ).not.toBeInTheDocument(),
      );
      expect(api.actionItemProposals.approve).toHaveBeenCalledExactlyOnceWith(
        1,
        { complete: true },
      );
      if (view === 'list')
        fireEvent.change(screen.getByRole('combobox', { name: 'Status' }), {
          target: { value: 'approved' },
        });
      expect(
        await screen.findByText('accepted as done', { exact: true }),
      ).toBeVisible();
      expect(api.actionItemProposals.approve).toHaveBeenCalledTimes(1);
    });

    it('does not publish an in-flight completion into an unmounted view', async () => {
      const response = deferred<ActionItemProposal>();
      vi.mocked(api.actionItemProposals.approve).mockReturnValue(
        response.promise,
      );
      const page = renderPage(view);
      await screen.findByRole('button', {
        name: `Complete ${proposal.target_name}`,
      });
      fireEvent.click(done());
      const before =
        vi.mocked(api.actionItemProposals.get).mock.calls.length +
        vi.mocked(api.actionItemProposals.list).mock.calls.length;
      page.unmount();
      await act(async () => response.resolve(completed()));
      expect(
        vi.mocked(api.actionItemProposals.get).mock.calls.length +
          vi.mocked(api.actionItemProposals.list).mock.calls.length,
      ).toBe(before);
    });

    it('shows the recorded Done outcome even after the live task was reopened', async () => {
      proposal = {
        ...completed(),
        current_target: {
          ...proposal.current_target,
          status: 'open',
          revision: 99,
        },
      };
      renderPage(view, true);
      expect(
        await screen.findByText('accepted as done', { exact: true }),
      ).toBeVisible();
      expect(
        screen.queryByRole('button', {
          name: `Complete ${proposal.target_name}`,
        }),
      ).not.toBeInTheDocument();
    });

    it('does not infer Done from a later completed task on an ordinary historical approval', async () => {
      proposal = {
        ...proposal,
        status: 'approved',
        review_outcome: 'accepted',
        applied_ref: { action_item_id: 12 },
        current_target: {
          ...proposal.current_target,
          status: 'completed',
          revision: 99,
        },
      };
      renderPage(view, true);
      await screen.findByText('approved', { exact: true });
      expect(
        screen.queryByText('accepted as done', { exact: true }),
      ).not.toBeInTheDocument();
    });
  });
}
