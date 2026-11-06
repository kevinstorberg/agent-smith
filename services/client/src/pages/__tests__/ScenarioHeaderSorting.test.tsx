import { fireEvent, screen, within, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router';
import { api } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { EvalSuiteDetailPage } from '../EvalSuiteDetailPage';
import { scenarioSortingRows } from './scenarioSortingFixture';

vi.mock('../../api', () => ({
  api: {
    evalConfigs: {
      suites: {
        get: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
        remove: vi.fn(),
      },
      scenarios: { update: vi.fn(), create: vi.fn(), remove: vi.fn() },
    },
  },
}));
const suite = {
  id: 1,
  name: 'Sorting suite',
  eval_type: 'rules',
  subcategory: 'sorting',
  judge_prompt: 'Complete judge context',
  items: {},
  config: {},
  enabled: true,
  created_at: '',
  updated_at: '',
  scenario_count: 3,
  scenarios: scenarioSortingRows,
};
async function ready() {
  renderWithProviders(
    <Routes>
      <Route path="/eval-configs/:id" element={<EvalSuiteDetailPage />} />
    </Routes>,
    { initialEntries: ['/eval-configs/1'] },
  );
  await screen.findByRole('heading', { name: 'Sorting suite' });
}
const names = () =>
  within(screen.getByRole('region', { name: 'Suite scenarios' }))
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[0].textContent);
let accepted: typeof suite;
beforeEach(() => {
  vi.clearAllMocks();
  accepted = structuredClone(suite);
  vi.mocked(api.evalConfigs.suites.get).mockResolvedValue(accepted);
  vi.mocked(api.evalConfigs.scenarios.update).mockResolvedValue(
    scenarioSortingRows[0],
  );
});
describe('Suite scenario header sorting', () => {
  it.each([
    ['Name', ['ALPHA', 'alpha', 'Zulu'], ['Zulu', 'ALPHA', 'alpha']],
    ['Prompt', ['ALPHA', 'alpha', 'Zulu'], ['Zulu', 'alpha', 'ALPHA']],
    ['Enabled', ['Zulu', 'ALPHA', 'alpha'], ['ALPHA', 'alpha', 'Zulu']],
  ])(
    'sorts complete %s values both ways without mutating canonical scenarios or calling APIs',
    async (label, ascending, descending) => {
      await ready();
      expect(names()).toEqual(['Zulu', 'alpha', 'ALPHA']);
      const header = screen.getByRole('columnheader', { name: label });
      const button = within(header).getByRole('button');
      button.focus();
      fireEvent.click(button);
      expect(names()).toEqual(ascending);
      expect(header).toHaveAttribute('aria-sort', 'ascending');
      fireEvent.click(button);
      expect(names()).toEqual(descending);
      expect(header).toHaveAttribute('aria-sort', 'descending');
      expect(button).toHaveFocus();
      expect(api.evalConfigs.suites.get).toHaveBeenCalledTimes(1);
      expect(api.evalConfigs.scenarios.update).not.toHaveBeenCalled();
      expect(api.evalConfigs.scenarios.remove).not.toHaveBeenCalled();
      expect(accepted.scenarios.map((row) => row.name)).toEqual([
        'Zulu',
        'alpha',
        'ALPHA',
      ]);
    },
  );

  it('preserves the expanded scenario editor and saves the correct identity after reordering', async () => {
    await ready();
    const row = screen.getByRole('cell', { name: 'Zulu' }).closest('tr')!;
    fireEvent.click(within(row).getByRole('button', { name: 'Edit scenario' }));
    const [name, prompt] = within(row).getAllByRole('textbox');
    fireEvent.change(name, { target: { value: 'Draft for Zulu' } });
    fireEvent.change(prompt, { target: { value: 'Complete unsaved prompt' } });
    fireEvent.click(screen.getByRole('button', { name: 'Name' }));
    expect(name).toHaveValue('Draft for Zulu');
    expect(prompt).toHaveValue('Complete unsaved prompt');
    expect(name.closest('tr')).toBe(row);
    fireEvent.click(within(row).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.evalConfigs.scenarios.update).toHaveBeenCalledWith(30, {
        name: 'Draft for Zulu',
        prompt: 'Complete unsaved prompt',
      }),
    );
    await screen.findByRole('cell', { name: 'Draft for Zulu' });
  });

  it('preserves an unsaved Add Scenario draft while headers change order', async () => {
    await ready();
    fireEvent.click(screen.getByRole('button', { name: '+ Add Scenario' }));
    const prompt = screen.getByPlaceholderText('Scenario prompt...');
    fireEvent.change(prompt, {
      target: { value: 'Complete unsaved new scenario prompt' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Enabled' }));
    expect(prompt).toHaveValue('Complete unsaved new scenario prompt');
    expect(api.evalConfigs.scenarios.create).not.toHaveBeenCalled();
  });
});
