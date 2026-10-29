import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { MeetingLabels } from '../MeetingLabels';
import { renderWithProviders } from '../../test-utils';
import { meetingFixture } from '../../pages/__tests__/meetingFixture';
vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: { meetings: { updateLabels: vi.fn(), suggestLabels: vi.fn() } } }));
import { api, ApiError } from '../../api';

const reload = vi.fn();
const meeting = { ...meetingFixture, labels: ['product'], labels_revision: 2, labels_source: 'agent' as const };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.meetings.updateLabels).mockResolvedValue({ labels: ['security'], labels_revision: 3, labels_source: 'human' });
  vi.mocked(api.meetings.suggestLabels).mockResolvedValue({ labels: ['security', 'paralign'], labels_revision: 2, meeting_revision: 7 });
});

it('previews suggestions and requires Save before applying labels with both revisions', async () => {
  renderWithProviders(<MeetingLabels meeting={meeting} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Suggest labels' }));
  await screen.findByText(/Suggestions are ready/);
  expect(api.meetings.suggestLabels).toHaveBeenCalledWith(meeting.id, 2);
  expect(api.meetings.updateLabels).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Meeting labels')).toHaveValue('security, paralign');
  fireEvent.change(screen.getByLabelText('Meeting labels'), { target: { value: 'security, operations' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save labels' }));
  await waitFor(() => expect(api.meetings.updateLabels).toHaveBeenCalledWith(meeting.id, {
    expected_revision: 2, labels: ['security', 'operations'], expected_meeting_revision: 7,
  }));
  expect(reload).toHaveBeenCalledTimes(1);
});

it('supports an intentional manual clear without assigning unrelated topics', async () => {
  renderWithProviders(<MeetingLabels meeting={meeting} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit labels' }));
  fireEvent.change(screen.getByLabelText('Meeting labels'), { target: { value: '' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save labels' }));
  await waitFor(() => expect(api.meetings.updateLabels).toHaveBeenCalledWith(meeting.id, { expected_revision: 2, labels: [] }));
});

it('retains a conflicted draft and uses the refreshed revision only after explicit retry', async () => {
  vi.mocked(api.meetings.updateLabels).mockRejectedValueOnce(new ApiError('Changed', 409));
  const { rerender } = renderWithProviders(<MeetingLabels meeting={meeting} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit labels' }));
  fireEvent.change(screen.getByLabelText('Meeting labels'), { target: { value: 'growth' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save labels' }));
  await screen.findByText(/This meeting or its labels changed/);
  rerender(<MeetingLabels meeting={{ ...meeting, labels: ['operations'], labels_revision: 4 }} onReload={reload} />);
  expect(screen.getByLabelText('Meeting labels')).toHaveValue('growth');
  expect(screen.getByText('Current labels: operations')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Save labels' }));
  await waitFor(() => expect(api.meetings.updateLabels).toHaveBeenLastCalledWith(meeting.id, { expected_revision: 4, labels: ['growth'] }));
});

it('retains manual input after a failed suggestion and can save it', async () => {
  vi.mocked(api.meetings.suggestLabels).mockRejectedValueOnce(new ApiError('Unavailable', 502));
  renderWithProviders(<MeetingLabels meeting={meeting} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit labels' }));
  fireEvent.change(screen.getByLabelText('Meeting labels'), { target: { value: 'roadmapping' } });
  fireEvent.click(screen.getByRole('button', { name: 'Suggest labels' }));
  await screen.findByText(/Could not suggest labels/);
  expect(screen.getByLabelText('Meeting labels')).toHaveValue('roadmapping');
  fireEvent.click(screen.getByRole('button', { name: 'Save labels' }));
  await waitFor(() => expect(api.meetings.updateLabels).toHaveBeenCalledWith(meeting.id, { expected_revision: 2, labels: ['roadmapping'] }));
});
