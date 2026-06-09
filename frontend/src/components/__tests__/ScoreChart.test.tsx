import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ScoreChart } from '../ScoreChart';

vi.mock('chart.js', () => ({
  Chart: { register: vi.fn() },
  CategoryScale: {}, LinearScale: {}, PointElement: {},
  LineElement: {}, Title: {}, Tooltip: {}, Legend: {},
}));
vi.mock('react-chartjs-2', () => ({
  Line: () => <div data-testid="chart" />,
}));

describe('ScoreChart', () => {
  it('shows "No data" for average mode with no data', () => {
    render(<ScoreChart mode="average" />);
    expect(screen.getByText('No data')).toBeInTheDocument();
  });

  it('shows "No data" for average mode with empty array', () => {
    render(<ScoreChart mode="average" averageData={[]} />);
    expect(screen.getByText('No data')).toBeInTheDocument();
  });

  it('renders chart for average mode with data', () => {
    render(<ScoreChart mode="average" averageData={[{ id: 1, timestamp: '2026-01-01T00:00:00Z', score: 0.9 }]} />);
    expect(screen.getByTestId('chart')).toBeInTheDocument();
  });

  it('shows "No data" for breakdown mode with no data', () => {
    render(<ScoreChart mode="breakdown" />);
    expect(screen.getByText('No data')).toBeInTheDocument();
  });

  it('renders chart for breakdown mode with data', () => {
    render(<ScoreChart mode="breakdown" data={[{ id: 1, timestamp: '2026-01-01T00:00:00Z', scores: { rule_1: 0.8 } }]} />);
    expect(screen.getByTestId('chart')).toBeInTheDocument();
  });
});
