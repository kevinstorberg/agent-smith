import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { AuditDetailPage } from '../AuditDetailPage';

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useParams: () => ({ id: '1' }) };
});

vi.mock('../../api', () => ({
  api: { audit: { get: vi.fn() } },
}));

import { api } from '../../api';

const mockGet = api.audit.get as ReturnType<typeof vi.fn>;

const fakeEvent = {
  id: 1,
  correlation_key: 'toolu_abc',
  agent: 'claude',
  session_id: 'sess-1',
  tool_name: 'Bash',
  cwd: '/Users/kevin/projects/agent-smith',
  project: 'agent-smith',
  status: 'success',
  created_at: '2026-06-15T10:00:00Z',
  completed_at: '2026-06-15T10:00:01Z',
  duration_ms: 1200,
  tool_input: { command: 'ls -la' },
  result: { stdout: 'total 0' },
};

beforeEach(() => {
  vi.clearAllMocks();
  mockGet.mockResolvedValue(fakeEvent);
});

describe('AuditDetailPage', () => {
  it('renders metadata and both payload panes for a completed event', async () => {
    renderWithProviders(<AuditDetailPage />);

    expect(await screen.findByText(/claude · Bash/)).toBeInTheDocument();
    expect(screen.getByText('toolu_abc')).toBeInTheDocument();
    expect(screen.getByText('1200 ms')).toBeInTheDocument();
    expect(screen.getByText('Tool input')).toBeInTheDocument();
    expect(screen.getByText('Result')).toBeInTheDocument();
    expect(screen.getByText(/ls -la/)).toBeInTheDocument();
    expect(screen.getByText(/total 0/)).toBeInTheDocument();
  });

  it('omits the result pane while still pending', async () => {
    mockGet.mockResolvedValue({ ...fakeEvent, status: 'pending', result: undefined });
    renderWithProviders(<AuditDetailPage />);

    await waitFor(() => expect(screen.getByText('Tool input')).toBeInTheDocument());
    expect(screen.queryByText('Result')).not.toBeInTheDocument();
  });
});
