import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '../../api';
import type { ProfileClaimsPage } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { profileFixture } from '../../pages/__tests__/profileFixture';
import { ProfileEvidence } from '../ProfileEvidence';
vi.mock('../../api', async (original) => ({
  ...(await original<typeof import('../../api')>()),
  api: { profiles: { claims: vi.fn(), correctClaim: vi.fn() } },
}));
const props = {
  profile: profileFixture,
  active: true,
  disabled: false,
  onBusyChange: vi.fn(),
  onReload: vi.fn(),
};
const page: ProfileClaimsPage = {
  profile_id: profileFixture.id,
  revision: 1,
  items: profileFixture.claims,
  total: 45,
};
const header = (name: string) => screen.getByRole('columnheader', { name });
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.profiles.claims).mockResolvedValue(page);
});
it.each([
  ['Observation', 'observation'],
  ['Type', 'type'],
  ['Confidence', 'confidence'],
  ['Review status', 'review'],
  ['Source', 'source'],
])(
  'toggles %s globally before paging while retaining filters',
  async (label, key) => {
    renderWithProviders(<ProfileEvidence {...props} />, {
      initialEntries: ['/?tab=evidence&category=perception&keep=1'],
    });
    await screen.findByText(page.items[0].content);
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() =>
      expect(api.profiles.claims).toHaveBeenLastCalledWith(
        profileFixture.id,
        expect.objectContaining({ offset: 20 }),
      ),
    );
    for (const direction of ['asc', 'desc']) {
      fireEvent.click(within(header(label)).getByRole('button'));
      await waitFor(() =>
        expect(api.profiles.claims).toHaveBeenLastCalledWith(
          profileFixture.id,
          {
            limit: 20,
            offset: 0,
            sort: `${key}_${direction}`,
            category: 'perception',
          },
        ),
      );
      await waitFor(() =>
        expect(header(label)).toHaveAttribute(
          'aria-sort',
          direction === 'asc' ? 'ascending' : 'descending',
        ),
      );
    }
    expect(screen.queryByLabelText('Sort')).not.toBeInTheDocument();
    expect(
      within(header('Details')).queryByRole('button'),
    ).not.toBeInTheDocument();
    expect(api.profiles.correctClaim).not.toHaveBeenCalled();
  },
);
it('retains corrected display text and focus during quiet sorting, then preserves a correction draft', async () => {
  const corrected = {
    ...page.items[0],
    status: 'corrected' as const,
    correction: {
      action: 'correct' as const,
      content: 'Human corrected observation',
      reason: 'Clarification',
      corrected_at: '2026-01-01T00:00:00Z',
    },
  };
  vi.mocked(api.profiles.claims).mockResolvedValue({
    ...page,
    items: [corrected],
  });
  renderWithProviders(<ProfileEvidence {...props} />);
  await screen.findByText('Human corrected observation');
  expect(
    within(screen.getByRole('table')).getByText('Perceptions'),
  ).toBeVisible();
  expect(screen.getByText('Hypothesis')).toBeVisible();
  expect(screen.getByText('Corrected by you')).toBeVisible();
  let finish!: (value: ProfileClaimsPage) => void;
  vi.mocked(api.profiles.claims).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const button = within(header('Observation')).getByRole('button');
  button.focus();
  fireEvent.click(button);
  await waitFor(() =>
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true'),
  );
  expect(screen.getByText('Human corrected observation')).toBeVisible();
  expect(screen.queryByText('Loading evidence...')).not.toBeInTheDocument();
  expect(button).toHaveFocus();
  await act(async () => finish({ ...page, items: [corrected] }));
  fireEvent.click(screen.getByRole('button', { name: 'View observation' }));
  fireEvent.click(screen.getByRole('button', { name: 'Correct claim' }));
  fireEvent.change(screen.getByLabelText('Corrected claim'), {
    target: { value: 'Retained draft' },
  });
  expect(button).toBeDisabled();
  expect(screen.getByLabelText('Corrected claim')).toHaveValue(
    'Retained draft',
  );
  expect(api.profiles.correctClaim).not.toHaveBeenCalled();
});

it('keeps failed-sort rows read-only and recovers through a busy header retry', async () => {
  renderWithProviders(<ProfileEvidence {...props} />);
  await screen.findByText(page.items[0].content);
  vi.mocked(api.profiles.claims).mockRejectedValueOnce(
    new Error('Unavailable'),
  );
  fireEvent.click(within(header('Observation')).getByRole('button'));
  await screen.findByRole('alert');
  expect(
    screen.getByRole('button', { name: 'View observation' }),
  ).toBeDisabled();
  expect(header('Observation')).not.toHaveAttribute('aria-sort');
  let finish!: (value: ProfileClaimsPage) => void;
  vi.mocked(api.profiles.claims).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const button = within(header('Observation')).getByRole('button');
  button.focus();
  fireEvent.click(button);
  await waitFor(() =>
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true'),
  );
  await act(async () => finish({ ...page, items: [], total: 0 }));
  expect(await screen.findByText(/No saved observations yet/)).toBeVisible();
  expect(header('Observation')).toHaveAttribute('aria-sort', 'descending');
  expect(button).toHaveFocus();
  expect(api.profiles.correctClaim).not.toHaveBeenCalled();
});
