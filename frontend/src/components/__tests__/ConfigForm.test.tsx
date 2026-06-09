import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ConfigForm } from '../ConfigForm';

function defaultProps(overrides = {}) {
  return {
    device: '*',
    repo: '*',
    agents: ['claude'],
    subagents: [],
    enabled: true,
    exclude: false,
    saving: false,
    onDeviceChange: vi.fn(),
    onRepoChange: vi.fn(),
    onAgentsChange: vi.fn(),
    onSubagentsChange: vi.fn(),
    onEnabledChange: vi.fn(),
    onExcludeChange: vi.fn(),
    onSave: vi.fn(),
    onCancel: vi.fn(),
    ...overrides,
  };
}

describe('ConfigForm', () => {
  it('renders title when provided', () => {
    render(<ConfigForm {...defaultProps({ title: 'Edit Config' })} />);
    expect(screen.getByText('Edit Config')).toBeInTheDocument();
  });

  it('shows validation error for invalid repo', () => {
    render(<ConfigForm {...defaultProps({ repo: 'bad/path' })} />);
    expect(screen.getByText(/absolute path/)).toBeInTheDocument();
  });

  it('does not show validation error for valid repo', () => {
    render(<ConfigForm {...defaultProps({ repo: '/valid/path' })} />);
    expect(screen.queryByText(/absolute path/)).toBeNull();
  });

  it('disables save when saving', () => {
    render(<ConfigForm {...defaultProps({ saving: true })} />);
    expect(screen.getByText('Saving...')).toBeDisabled();
  });

  it('disables save when repo is invalid', () => {
    render(<ConfigForm {...defaultProps({ repo: 'invalid' })} />);
    expect(screen.getByText('Save')).toBeDisabled();
  });

  it('calls onAgentsChange when agent checkbox toggled', () => {
    const onAgentsChange = vi.fn();
    render(<ConfigForm {...defaultProps({ agents: ['claude'], onAgentsChange })} />);
    const codexCheckboxes = screen.getAllByLabelText('codex');
    fireEvent.click(codexCheckboxes[0]); // First one is in Agents section
    expect(onAgentsChange).toHaveBeenCalledWith(['claude', 'codex']);
  });

  it('calls onCancel when cancel clicked', () => {
    const onCancel = vi.fn();
    render(<ConfigForm {...defaultProps({ onCancel })} />);
    fireEvent.click(screen.getByText('Cancel'));
    expect(onCancel).toHaveBeenCalled();
  });

  it('uses custom submitLabel', () => {
    render(<ConfigForm {...defaultProps({ submitLabel: 'Create' })} />);
    expect(screen.getByText('Create')).toBeInTheDocument();
  });

  it('calls onSubagentsChange when subagent checkbox toggled', () => {
    const onSubagentsChange = vi.fn();
    render(<ConfigForm {...defaultProps({ subagents: [], onSubagentsChange })} />);
    const codexCheckboxes = screen.getAllByLabelText('codex');
    fireEvent.click(codexCheckboxes[1]); // Second one is in Subagents section
    expect(onSubagentsChange).toHaveBeenCalledWith(['codex']);
  });
});
