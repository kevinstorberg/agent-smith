import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { MeetingsIndexPage } from '../MeetingsIndexPage';
import { meetingFixture } from './meetingFixture';

const mockNavigate = vi.fn();

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: { meetings: { list: vi.fn(), vocabulary: { list: vi.fn() } } } }));
import { api } from '../../api';

const mockList = vi.mocked(api.meetings.list);
const meetings = [meetingFixture, { ...meetingFixture, id: 'other-id', source_name: 'team', title: 'Team retrospective' }];

beforeEach(() => {
  vi.clearAllMocks();
  mockList.mockResolvedValue({ items: meetings, total: 2 });
  vi.mocked(api.meetings.vocabulary.list).mockResolvedValue({ items: [], total: 0 });
});

describe('MeetingsIndexPage', () => {
  it('shows summaries from multiple connections without a source or device filter', async () => {
    renderWithProviders(<MeetingsIndexPage />);

    expect(await screen.findByText('Product planning')).toBeInTheDocument();
    expect(screen.getByText('Team retrospective')).toBeInTheDocument();
    expect(screen.getByText('personal')).toBeInTheDocument();
    expect(screen.getByText('team')).toBeInTheDocument();
    expect(mockList).toHaveBeenCalledWith({ limit: 10, offset: 0, q: undefined });
  });

  it('opens the selected summary with keyboard navigation', async () => {
    renderWithProviders(<MeetingsIndexPage />);
    const title = await screen.findByText('Product planning');
    fireEvent.keyDown(title.closest('tr')!, { key: 'Enter' });

    expect(mockNavigate).toHaveBeenCalledWith(`/meetings/${meetingFixture.id}`);
  });

  it('searches and clears while keeping pagination on the server', async () => {
    mockList.mockResolvedValue({ items: meetings, total: 25 });
    renderWithProviders(<MeetingsIndexPage />);
    await screen.findByText('Product planning');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(mockList).toHaveBeenLastCalledWith({ limit: 10, offset: 10, q: undefined }));

    fireEvent.change(screen.getByLabelText('Search meetings'), { target: { value: ' release ' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Search' }).closest('form')!);
    await waitFor(() => expect(mockList).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: 'release' }));

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await waitFor(() => expect(mockList).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: undefined }));
  });

  it('distinguishes loading, empty imports and search results', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<MeetingsIndexPage />);
    expect(screen.getByText('Loading meetings...')).toBeInTheDocument();
    expect(await screen.findByText(/No meeting summaries saved yet/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Search meetings'), { target: { value: 'missing' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Search' }).closest('form')!);
    expect(await screen.findByText('No meetings match your search.')).toBeInTheDocument();
  });

  it('shows a failed import reader separately from an empty list and can retry', async () => {
    mockList.mockRejectedValueOnce(new Error('Storage unavailable'));
    renderWithProviders(<MeetingsIndexPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load meetings: Storage unavailable');
    expect(screen.queryByText(/No meeting summaries saved yet/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Product planning')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
