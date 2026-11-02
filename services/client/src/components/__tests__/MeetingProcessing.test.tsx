import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import type { MeetingTranscript, MeetingMemories, MeetingProfiles } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { MeetingProcessing } from '../MeetingProcessing';
vi.mock('../../api', () => ({ api: { meetings: { process: vi.fn(), retryMemories: vi.fn(), retryProfiles: vi.fn() } } }));
import { api } from '../../api';
const transcript: MeetingTranscript = { status: 'ready', items: [], total: 0, offset: 0, limit: 100, error_type: null, captured_at: null };
const memories: MeetingMemories = { status: 'pending', items: [], reason: null, error_type: null, updated_at: null,
  progress: { processed_units: 100, total_units: 300, staged_count: 8, saved_count: 0, attempts: 0, next_attempt_at: null } };
const personas: MeetingProfiles = { status: 'pending', items: [], reason: null, error_type: null };
const changed = vi.fn();
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.meetings.process).mockResolvedValue({ status: 'queued' }); vi.mocked(api.meetings.retryMemories).mockResolvedValue({ success: true }); });

it('shows checkpoint progress and queues a resume without claiming staged candidates are published', async () => {
  renderWithProviders(<MeetingProcessing meetingId="meeting-id" transcript={transcript} memories={memories} personas={personas} onChanged={changed} />);
  expect(screen.getByRole('progressbar', { name: 'Memory analysis progress' })).toHaveValue(100);
  expect(screen.getByText('100 of 300 summary sections analyzed')).toBeInTheDocument();
  expect(screen.getByText('8 candidates saved · 0 memories published')).toBeInTheDocument();
  expect(screen.getByText('Automatic processing continues from its saved summary progress.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Continue processing' }));
  await waitFor(() => expect(api.meetings.process).toHaveBeenCalledWith('meeting-id'));
  expect(changed).toHaveBeenCalledTimes(1);
});

it('keeps persona state independent when memories fail and allows a memory-only retry during persona work', async () => {
  renderWithProviders(<MeetingProcessing meetingId="meeting-id" transcript={transcript} memories={{ ...memories, status: 'failed' }} personas={{ ...personas, status: 'running' }} onChanged={changed} />);
  expect(screen.getByRole('button', { name: 'Processing...' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Retry memories' }));
  await waitFor(() => expect(api.meetings.retryMemories).toHaveBeenCalledWith('meeting-id'));
  expect(api.meetings.retryProfiles).not.toHaveBeenCalled();
  expect(await screen.findByRole('status')).toHaveTextContent('Memory retry queued. Restart from the beginning using the saved Granola summary.');
  expect(screen.getByText(/run independently/)).toBeInTheDocument();
});

it('keeps completed outputs intact and offers a separate explicit reanalysis control', () => {
  renderWithProviders(<MeetingProcessing meetingId="meeting-id" transcript={transcript} memories={{ ...memories, status: 'done' }} personas={{ ...personas, status: 'done' }} onChanged={changed} />);
  expect(screen.getByRole('button', { name: 'Processing complete' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Reanalyze completed...' })).toBeEnabled();
  expect(api.meetings.process).not.toHaveBeenCalled();
});

it('respects parent editing and unread status for stage retry buttons', () => {
  const { rerender } = renderWithProviders(<MeetingProcessing meetingId="meeting-id" disabled transcript={transcript} memories={{ ...memories, status: 'failed' }} personas={personas} onChanged={changed} />);
  expect(screen.getByRole('button', { name: 'Retry memories' })).toBeDisabled();
  rerender(<MeetingProcessing meetingId="meeting-id" transcript={null} memories={{ ...memories, status: 'failed' }} personas={personas} onChanged={changed} />);
  expect(screen.getByRole('button', { name: 'Retry memories' })).toBeDisabled();
});

it('allows processing and memory retries after transcript capture without a speaker stage', async () => {
  renderWithProviders(<MeetingProcessing meetingId="meeting-id" transcript={transcript} memories={{ ...memories, status: 'failed' }} personas={{ ...personas, status: 'done' }} onChanged={changed} />);
  expect(screen.getByRole('button', { name: 'Continue processing' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Reanalyze completed...' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Retry memories' }));
  await waitFor(() => expect(api.meetings.retryMemories).toHaveBeenCalledWith('meeting-id'));
});

it('shows saved persona progress in the badge and explains its last timeout', () => {
  renderWithProviders(<MeetingProcessing meetingId="meeting-id" transcript={transcript} memories={{ ...memories, status: 'done' }} personas={{ ...personas,
    error_type: 'ModelCallTimeoutError', progress: { ...memories.progress!, processed_units: 300, total_units: 679, staged_count: 33, attempts: 2 },
  }} onChanged={changed} />);
  expect(screen.getByRole('link', { name: 'Profiles: Progress saved' })).toHaveAttribute('href', '#meeting-profiles');
  fireEvent.click(screen.getByText('Processing details'));
  expect(screen.getByRole('progressbar', { name: 'Profile analysis progress' })).toHaveValue(300);
  expect(screen.getByRole('status')).toHaveTextContent('The last attempt timed out. Saved progress is kept.');
});

it('shows only current workflows and keeps completed processing complete', () => {
  renderWithProviders(<MeetingProcessing meetingId="meeting-id" transcript={transcript} memories={{ ...memories, status: 'done' }} personas={{ ...personas, status: 'done' }} onChanged={changed} />);
  expect(screen.getByRole('button', { name: 'Processing complete' })).toBeDisabled();
  expect(screen.queryByRole('link', { name: /Speakers:|Review speakers/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('Processing details'));
  expect(screen.queryByText('Speaker identification')).not.toBeInTheDocument();
  expect(screen.queryByText(/statements reviewed|Next eligible attempt/)).not.toBeInTheDocument();
  expect(api.meetings.process).not.toHaveBeenCalled();
});

it('keeps profile-only retry notices about preserved work and never describes a memory restart', async () => {
  vi.mocked(api.meetings.retryProfiles).mockResolvedValue({ success: true });
  renderWithProviders(<MeetingProcessing meetingId="meeting-id" transcript={transcript} memories={{ ...memories, status: 'done' }} personas={{ ...personas, status: 'failed' }} onChanged={changed} />);
  fireEvent.click(screen.getByRole('button', { name: 'Retry profiles' }));
  await waitFor(() => expect(api.meetings.retryProfiles).toHaveBeenCalledWith('meeting-id'));
  expect(await screen.findByRole('status')).toHaveTextContent('Retry queued. Completed work is preserved.');
  expect(api.meetings.retryMemories).not.toHaveBeenCalled();
  expect(screen.queryByText(/Restart from the beginning/)).not.toBeInTheDocument();
});
