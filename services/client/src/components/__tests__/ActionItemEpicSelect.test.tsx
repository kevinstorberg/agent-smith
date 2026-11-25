import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ActionItemEpicSelect } from '../ActionItemEpicSelect';
import { epicGroup } from '../../pages/__tests__/actionItemEpicFixture';

describe('controlled Epic selection', () => {
  it('disambiguates duplicate names and changes only through its owner', () => {
    const first = epicGroup(10, []).epic;
    const second = { ...epicGroup(20, []).epic, title: first.title };
    const onChange = vi.fn();
    render(
      <ActionItemEpicSelect
        label="Epic"
        value=""
        epics={[first, second]}
        onChange={onChange}
      />,
    );
    expect(
      screen.getByRole('option', { name: `${first.title} #10` }),
    ).toHaveValue('10');
    expect(
      screen.getByRole('option', { name: `${first.title} #20` }),
    ).toHaveValue('20');
    expect(
      screen.queryByRole('option', { name: 'New Epic…' }),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '20' } });
    expect(onChange).toHaveBeenCalledExactlyOnceWith('20');
    expect(screen.getByRole('combobox')).toHaveValue('');
    expect(screen.getByRole('combobox')).not.toHaveFocus();
  });

  it('keeps an earlier choice visible alongside fresh options for explicit reselection', () => {
    const epic = epicGroup(10, []).epic;
    const onChange = vi.fn();
    render(
      <ActionItemEpicSelect
        label="Epic"
        value="earlier"
        defaultLabel="Keep current Epic"
        epics={[{ ...epic, title: 'Renamed release' }]}
        retainedOption={{ value: 'earlier', label: 'Release — earlier choice' }}
        onChange={onChange}
      />,
    );
    expect(screen.getByRole('combobox')).toHaveDisplayValue(
      'Release — earlier choice',
    );
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '10' } });
    expect(onChange).toHaveBeenCalledExactlyOnceWith('10');
  });
});
