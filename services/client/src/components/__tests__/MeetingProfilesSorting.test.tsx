import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingProfiles as Profiles } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { profileFixture } from '../../pages/__tests__/profileFixture';
import { deferred } from '../../pages/__tests__/actionItemFixture';
import { MeetingProfiles } from '../MeetingProfiles';

vi.mock('../../api', () => ({
  api: { meetings: { profiles: vi.fn(), retryProfiles: vi.fn() } },
}));
import { api } from '../../api';
const rows = Object.freeze([
  Object.freeze({
    ...profileFixture,
    id: 'profile-3',
    display_name: 'Zulu',
    email: 'b@example.test',
  }),
  Object.freeze({
    ...profileFixture,
    id: 'profile-2',
    display_name: 'alpha',
    email: null,
  }),
  Object.freeze({
    ...profileFixture,
    id: 'profile-1',
    display_name: 'ALPHA',
    email: 'a@example.test',
  }),
  Object.freeze({
    ...profileFixture,
    id: 'profile-4',
    display_name: 'bravo',
    email: '',
  }),
]);
const result = (items: Profiles['items'] = [...rows]): Profiles => ({
  status: 'done',
  items,
  reason: null,
  error_type: null,
});
const names = () =>
  within(screen.getByRole('table', { name: 'Linked participant profiles' }))
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[0].textContent);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.meetings.profiles).mockResolvedValue(result());
});

describe('Linked meeting profiles sorting', () => {
  it.each([
    [
      'Name',
      ['ALPHA', 'alpha', 'bravo', 'Zulu'],
      ['Zulu', 'bravo', 'ALPHA', 'alpha'],
    ],
    [
      'Email',
      ['ALPHA', 'Zulu', 'alpha', 'bravo'],
      ['Zulu', 'ALPHA', 'alpha', 'bravo'],
    ],
  ])(
    'sorts the full %s snapshot both ways with stable ties and missing values last',
    async (label, ascending, descending) => {
      renderWithProviders(<MeetingProfiles meetingId="one" />);
      await screen.findByRole('link', { name: "View Zulu's profile" });
      expect(names()).toEqual(['Zulu', 'alpha', 'ALPHA', 'bravo']);
      const header = screen.getByRole('columnheader', {
        name: label,
      });
      const button = within(header).getByRole('button');
      button.focus();
      fireEvent.click(button);
      expect(names()).toEqual(ascending);
      expect(header).toHaveAttribute('aria-sort', 'ascending');
      fireEvent.click(button);
      expect(names()).toEqual(descending);
      expect(header).toHaveAttribute('aria-sort', 'descending');
      expect(button).toHaveFocus();
      expect(api.meetings.profiles).toHaveBeenCalledTimes(1);
      expect(api.meetings.retryProfiles).not.toHaveBeenCalled();
      expect(rows.map((row) => row.display_name)).toEqual([
        'Zulu',
        'alpha',
        'ALPHA',
        'bravo',
      ]);
      expect(
        within(
          screen.getByRole('columnheader', { name: 'Actions' }),
        ).queryByRole('button'),
      ).not.toBeInTheDocument();
    },
  );

  it('retains the chosen local order when the same meeting refreshes', async () => {
    const view = renderWithProviders(
      <MeetingProfiles meetingId="one" refreshVersion={0} />,
    );
    await screen.findByRole('link', { name: "View Zulu's profile" });
    fireEvent.click(screen.getByRole('button', { name: 'Name' }));
    vi.mocked(api.meetings.profiles).mockResolvedValue(
      result([{ ...rows[0], display_name: 'aardvark' }, rows[1]]),
    );
    view.rerender(<MeetingProfiles meetingId="one" refreshVersion={1} />);
    await screen.findByRole('link', { name: "View aardvark's profile" });
    expect(names()).toEqual(['aardvark', 'alpha']);
    expect(screen.getByRole('columnheader', { name: 'Name' })).toHaveAttribute(
      'aria-sort',
      'ascending',
    );
  });

  it('resets local sort and pending reads when the meeting identity changes', async () => {
    const next = deferred<Profiles>();
    const view = renderWithProviders(<MeetingProfiles meetingId="one" />);
    await screen.findByRole('link', { name: "View Zulu's profile" });
    fireEvent.click(screen.getByRole('button', { name: 'Name' }));
    vi.mocked(api.meetings.profiles).mockReturnValueOnce(next.promise);
    view.rerender(<MeetingProfiles meetingId="two" />);
    expect(
      screen.queryByRole('link', { name: "View Zulu's profile" }),
    ).not.toBeInTheDocument();
    await act(async () => next.resolve(result()));
    await waitFor(() =>
      expect(names()).toEqual(['Zulu', 'alpha', 'ALPHA', 'bravo']),
    );
    expect(
      screen.getByRole('columnheader', { name: 'Name' }),
    ).not.toHaveAttribute('aria-sort');
    expect(api.meetings.profiles).toHaveBeenLastCalledWith('two');
  });
});
