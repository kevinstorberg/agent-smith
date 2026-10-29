import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { useLocation } from 'react-router';
import { MeetingsIndexPage } from '../MeetingsIndexPage';
import { meetingFixture } from './meetingFixture';

const mockNavigate = vi.fn();

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: { meetings: { list: vi.fn(), vocabulary: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() } } } }));
import { api } from '../../api';

const mockList = vi.mocked(api.meetings.list);
const meetings = [meetingFixture, { ...meetingFixture, id: 'other-id', source_name: 'team', title: 'Team retrospective' }];
const term = { id: 'term-1', term: 'LTV', definition: 'Lifetime value', revision: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' };

function Location() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockList.mockResolvedValue({ items: meetings, total: 2 });
  vi.mocked(api.meetings.vocabulary.list).mockResolvedValue({ items: [], total: 0 });
});

describe('MeetingsIndexPage', () => {
  it('opens Vocabulary from its URL and preserves unrelated query parameters when switching views', async () => {
    vi.mocked(api.meetings.vocabulary.list).mockResolvedValue({ items: [term], total: 1 });
    renderWithProviders(<><MeetingsIndexPage /><Location /></>, { initialEntries: ['/meetings?tab=vocabulary&source=work'] });
    expect(await screen.findByRole('button', { name: 'Edit LTV' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Vocabulary' })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByRole('textbox', { name: 'Search meetings' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Meetings' }));
    expect(screen.getByRole('textbox', { name: 'Search meetings' })).toBeVisible();
    expect(screen.getByTestId('location')).toHaveTextContent('/meetings?tab=meetings&source=work');
    expect(screen.queryByRole('button', { name: 'Edit LTV' })).not.toBeInTheDocument();
  });

  it('retains meeting search, pagination and an unsaved vocabulary edit across tab changes', async () => {
    mockList.mockResolvedValue({ items: meetings, total: 25 });
    vi.mocked(api.meetings.vocabulary.list).mockResolvedValue({ items: [term], total: 1 });
    renderWithProviders(<MeetingsIndexPage />);
    await screen.findByText('Product planning');
    fireEvent.change(screen.getByRole('textbox', { name: 'Search meetings' }), { target: { value: 'release' } });
    await waitFor(() => expect(mockList).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: 'release' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(mockList).toHaveBeenLastCalledWith({ limit: 10, offset: 10, q: 'release' }));
    const listReads = mockList.mock.calls.length;
    fireEvent.click(screen.getByRole('link', { name: 'Vocabulary' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Edit LTV' }));
    fireEvent.change(screen.getByLabelText('Meaning / definition (optional)'), { target: { value: 'My definition draft' } });
    fireEvent.click(screen.getByRole('link', { name: 'Meetings' }));
    expect(screen.getByRole('textbox', { name: 'Search meetings' })).toHaveValue('release');
    expect(screen.getByText('Showing 11–20 of 25')).toBeVisible();
    expect(mockList).toHaveBeenCalledTimes(listReads);
    fireEvent.click(screen.getByRole('link', { name: 'Vocabulary' }));
    expect(screen.getByLabelText('Meaning / definition (optional)')).toHaveValue('My definition draft');
    expect(api.meetings.vocabulary.update).not.toHaveBeenCalled();
  });

  it('renders meeting topics and filters them while typing from the first page', async () => {
    mockList.mockResolvedValue({ items: [{ ...meetingFixture, labels: ['product', 'roadmapping'] }], total: 1 });
    renderWithProviders(<MeetingsIndexPage />);
    expect(await screen.findByText('roadmapping')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Filter meetings by labels'), { target: { value: 'product, roadmapping' } });
    await waitFor(() => expect(mockList).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: undefined, labels: ['product', 'roadmapping'] }));
  });
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
