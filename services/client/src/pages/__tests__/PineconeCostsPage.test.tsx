import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CostsPage } from '../CostsPage';
import { api } from '../../api';
import source from './pineconeCostsFixture.json?raw';
import type { CostReport, CostResponse } from '../../types/costs';

vi.mock('../../api', () => ({ api: { costs: { get: vi.fn() } } }));
const fixture = JSON.parse(source) as {
  baseline: CostReport;
  observed: CostReport;
  no_price: CostReport;
};
const aws: CostReport = {
  ...fixture.observed,
  provider: 'aws',
  total: '12.25',
  scope: 'AWS visible account',
  cost_basis: 'UnblendedCost',
  usage: [],
  notes: [],
};
const ready = (report: CostReport): CostResponse => ({
  state: 'ready',
  report,
  error: null,
});

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.costs.get).mockImplementation(async (provider) =>
    ready(provider === 'aws' ? aws : fixture.observed),
  );
});
afterEach(() => {
  vi.useRealTimers();
});

async function pinecone() {
  render(<CostsPage />);
  await screen.findByText('AWS visible account');
  fireEvent.click(screen.getByRole('button', { name: 'Pinecone' }));
}

describe('Pinecone observed usage view', () => {
  it('shows a forward estimate, exact subcent amount, quantities and separate commitment', async () => {
    await pinecone();
    expect(
      await screen.findByRole('heading', { name: 'Observed usage estimate' }),
    ).toBeVisible();
    expect(screen.getByText('$0.00006', { selector: 'strong' })).toBeVisible();
    expect(
      screen.getByRole('region', { name: 'Observed usage' }),
    ).toBeVisible();
    expect(screen.getByText('10 RU')).toBeVisible();
    expect(screen.getByText('4096 bytes')).toBeVisible();
    expect(
      screen.getByText(/Standard monthly commitment: USD 50/),
    ).toBeVisible();
    expect(screen.queryByText('AWS visible account')).not.toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Configured pricing source' }),
    ).toHaveAttribute('href', 'https://www.pinecone.io/pricing/');
    expect(screen.getByText(/rate reference date: 2026-11-05/i)).toBeVisible();
    expect(screen.queryByText(/verified 2026-11-05/i)).not.toBeInTheDocument();
  });

  it('shows baseline history and costs unavailable without inventing zero', async () => {
    vi.mocked(api.costs.get).mockImplementation(async (provider) =>
      ready(provider === 'aws' ? aws : fixture.baseline),
    );
    await pinecone();
    expect(
      await screen.findByText('Cost unavailable for this period'),
    ).toBeVisible();
    expect(
      screen.getByText(/History before the monitoring baseline is unavailable/),
    ).toBeVisible();
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument();
    expect(screen.getByText(/Observed since:/)).toBeVisible();
    expect(
      within(
        screen.getByRole('region', { name: 'Observed usage' }),
      ).getAllByText('Unavailable'),
    ).toHaveLength(2);
  });

  it('keeps quantities visible with no configured rates', async () => {
    vi.mocked(api.costs.get).mockImplementation(async (provider) =>
      ready(provider === 'aws' ? aws : fixture.no_price),
    );
    await pinecone();
    await screen.findByText(/Configure dated cloud\/region prices/);
    expect(screen.getByText('10 RU')).toBeVisible();
    expect(screen.getByText('Cost unavailable for this period')).toBeVisible();
  });

  it('keeps a provider configuration error local to that selected provider', async () => {
    vi.mocked(api.costs.get).mockImplementation(async (provider) =>
      provider === 'aws'
        ? ready(aws)
        : {
            state: 'not_configured',
            report: null,
            error: {
              code: 'configuration_error',
              message: 'Configure PINECONE_PROJECT_ID and PINECONE_API_KEY.',
            },
          },
    );
    await pinecone();
    await screen.findByText(/Configure PINECONE_PROJECT_ID/);
    expect(screen.queryByText('$12.25')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'AWS' }));
    expect(
      await screen.findByText('$12.25', { selector: 'strong' }),
    ).toBeVisible();
    expect(screen.getByText('Estimated charges')).toBeVisible();
  });

  it('rejects an AWS response captured before switching to Pinecone', async () => {
    let finish!: (value: CostResponse) => void;
    vi.mocked(api.costs.get).mockImplementation((provider) =>
      provider === 'aws'
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : Promise.resolve(ready(fixture.observed)),
    );
    render(<CostsPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Pinecone' }));
    await screen.findByText('$0.00006', { selector: 'strong' });
    await act(async () => {
      finish(ready(aws));
    });
    expect(screen.queryByText('AWS visible account')).not.toBeInTheDocument();
    expect(screen.getByText('$0.00006', { selector: 'strong' })).toBeVisible();
  });

  it('polls only the selected cached endpoint and stops on unmount', async () => {
    vi.useFakeTimers();
    const view = render(<CostsPage />);
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Pinecone' }));
    await act(async () => {
      await Promise.resolve();
    });
    const before = vi.mocked(api.costs.get).mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    expect(api.costs.get).toHaveBeenLastCalledWith('pinecone');
    expect(api.costs.get).toHaveBeenCalledTimes(before + 1);
    view.unmount();
    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    expect(api.costs.get).toHaveBeenCalledTimes(before + 1);
  });
});
