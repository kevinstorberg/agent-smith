import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { metadataOptionsFixture, profileFixture } from '../../pages/__tests__/profileFixture';
import { ProfileMetadata } from '../ProfileMetadata';

vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: { profiles: { update: vi.fn(), metadataOptions: vi.fn() } } };
});
import { api, ApiError } from '../../api';
const reload = vi.fn();
const busy = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.profiles.update).mockResolvedValue(profileFixture);
  vi.mocked(api.profiles.metadataOptions).mockResolvedValue(metadataOptionsFixture);
});

describe('ProfileMetadata', () => {
  it('shows all metadata fields with source links and distinguishes human-owned fields', () => {
    renderWithProviders(<ProfileMetadata profile={{ ...profileFixture, metadata: { company: 'Paralign', job_role: 'Engineering lead' },
      metadata_provenance: { company: { meeting_id: 'meeting-source', transcript_hash: 'hash', participants_revision: 0,
        evidence: [{ segment_id: 'segment-4', quote: 'I work at Paralign.' }] }, job_role: { human: true } } }}
      disabled={false} onBusyChange={busy} onReload={reload} />);
    expect(screen.getByText('Paralign')).toBeInTheDocument();
    expect(screen.queryByText('I work at Paralign.')).not.toBeInTheDocument();
    expect(screen.getAllByText('Not set')).toHaveLength(6);
    expect(screen.getByText('Edited by you')).toBeInTheDocument();
    expect(screen.getByText('View source meeting')).toHaveAttribute('href', '/meetings/meeting-source#meeting-transcript');
    expect(api.profiles.metadataOptions).not.toHaveBeenCalled();
  });

  it('saves a normalized name, tags and a star with the captured revision', async () => {
    renderWithProviders(<ProfileMetadata profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: ' Alex Morgan ' } });
    fireEvent.change(screen.getByLabelText('Tags'), { target: { value: ' team, priority,team , ' } });
    fireEvent.click(screen.getByLabelText('Starred'));
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenCalledWith(profileFixture.id, { expected_revision: 1, display_name: 'Alex Morgan', tags: ['team', 'priority'], starred: true }));
    expect(reload).toHaveBeenCalled();
    expect(vi.mocked(api.profiles.update).mock.calls[0][1]).not.toHaveProperty('metadata');
  });

  it('sends only a deliberately cleared metadata field and preserves untouched empty fields for autofill', async () => {
    renderWithProviders(<ProfileMetadata profile={{ ...profileFixture, metadata: { company: 'Paralign', job_role: 'Engineer' } }}
      disabled={false} onBusyChange={busy} onReload={reload} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    fireEvent.change(screen.getByLabelText('Company'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenCalledWith(profileFixture.id,
      expect.objectContaining({ metadata: { company: '' } })));
    expect(vi.mocked(api.profiles.update).mock.calls[0][1].metadata).toEqual({ company: '' });
  });

  it('preserves a metadata draft across a conflict and requires an explicit retry', async () => {
    vi.mocked(api.profiles.update).mockRejectedValueOnce(new ApiError('Private detail', 409));
    const { rerender } = renderWithProviders(<ProfileMetadata profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'My name draft' } });
    fireEvent.change(screen.getByLabelText('Tags'), { target: { value: 'my draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Review the latest version and save again.');
    rerender(<ProfileMetadata profile={{ ...profileFixture, display_name: 'Changed elsewhere', revision: 2 }} disabled={false} onBusyChange={busy} onReload={reload} />);
    expect(screen.getByLabelText('Name')).toHaveValue('My name draft');
    expect(screen.getByLabelText('Tags')).toHaveValue('my draft');
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenLastCalledWith(profileFixture.id, { expected_revision: 2, display_name: 'My name draft', tags: ['my draft'], starred: false }));
  });

  it('requires a nonblank name and cancels without changing the profile', async () => {
    renderWithProviders(<ProfileMetadata profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    expect(screen.getByRole('alert')).toHaveTextContent('A profile name is required.');
    expect(api.profiles.update).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    expect(screen.getByLabelText('Name')).toHaveValue('Alex');
    await waitFor(() => expect(screen.getByLabelText('Gender')).toBeEnabled());
  });

  it('uses server choices for optional selects and submits only deliberately changed fields', async () => {
    renderWithProviders(<ProfileMetadata profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    const gender = screen.getByRole('combobox', { name: 'Gender' });
    const marital = screen.getByRole('combobox', { name: 'Marital status' });
    await waitFor(() => expect(gender).toBeEnabled());
    expect(gender).toHaveValue('');
    expect(marital).toHaveValue('');
    expect(gender).not.toBeRequired();
    expect(marital).not.toBeRequired();
    fireEvent.change(gender, { target: { value: 'Female' } });
    fireEvent.change(marital, { target: { value: 'Married' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenCalledWith(profileFixture.id,
      expect.objectContaining({ metadata: { gender: 'Female', marital_status: 'Married' } })));
  });

  it('preserves legacy choices on unrelated edits and supports explicitly clearing one', async () => {
    const profile = { ...profileFixture, metadata: { gender: 'Existing custom value', marital_status: 'Married' } };
    renderWithProviders(<ProfileMetadata profile={profile} disabled={false} onBusyChange={busy} onReload={reload} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    await waitFor(() => expect(screen.getByLabelText('Gender')).toBeEnabled());
    expect(screen.getByRole('option', { name: 'Existing custom value (existing value)' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Company'), { target: { value: 'Paralign' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenLastCalledWith(profile.id,
      expect.objectContaining({ metadata: { company: 'Paralign' } })));
    await screen.findByRole('button', { name: 'Edit profile' });
    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    await waitFor(() => expect(screen.getByLabelText('Gender')).toBeEnabled());
    fireEvent.change(screen.getByLabelText('Gender'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenLastCalledWith(profile.id,
      expect.objectContaining({ metadata: { gender: '' } })));
  });

  it('retries unavailable choices without discarding other profile edits', async () => {
    vi.mocked(api.profiles.metadataOptions).mockRejectedValueOnce(new Error('Private upstream detail'));
    renderWithProviders(<ProfileMetadata profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    fireEvent.change(screen.getByLabelText('Company'), { target: { value: 'Company draft' } });
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load metadata choices.');
    expect(screen.queryByText('Private upstream detail')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Gender')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByLabelText('Gender')).toBeEnabled());
    expect(screen.getByLabelText('Company')).toHaveValue('Company draft');
  });

  it('can restore the exact legacy selection after trying a standard choice in the same draft', async () => {
    const legacy = '  Existing custom value  ';
    renderWithProviders(<ProfileMetadata profile={{ ...profileFixture, metadata: { gender: legacy } }}
      disabled={false} onBusyChange={busy} onReload={reload} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    const gender = screen.getByRole('combobox', { name: 'Gender' });
    await waitFor(() => expect(gender).toBeEnabled());
    fireEvent.change(gender, { target: { value: 'Female' } });
    expect(screen.getByRole('option', { name: 'Existing custom value (existing value)' })).toHaveValue(legacy);
    fireEvent.change(gender, { target: { value: legacy } });
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenLastCalledWith(profileFixture.id,
      expect.objectContaining({ metadata: { gender: legacy } })));
  });

  it('patches only edited optional metadata keys and deduplicates nickname aliases', async () => {
    const { rerender } = renderWithProviders(<ProfileMetadata profile={{ ...profileFixture, metadata: { company: 'Original', job_role: 'Engineer' } }} disabled={false} onBusyChange={busy} onReload={reload} />);
    vi.mocked(api.profiles.update).mockRejectedValueOnce(new ApiError('Conflict', 409));
    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    fireEvent.change(screen.getByLabelText('Company'), { target: { value: ' My company ' } });
    fireEvent.change(screen.getByLabelText('Nicknames'), { target: { value: 'Alex, alex, Lex' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    await screen.findByRole('alert');
    rerender(<ProfileMetadata profile={{ ...profileFixture, revision: 2, metadata: { company: 'Other company', job_role: 'Manager' } }} disabled={false} onBusyChange={busy} onReload={reload} />);
    expect(screen.getByLabelText('Company')).toHaveValue(' My company ');
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenLastCalledWith(profileFixture.id, expect.objectContaining({ expected_revision: 2, metadata: { company: 'My company' }, nicknames: ['Alex', 'Lex'] })));
  });
});
