import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import type { ChartPoint, AverageChartPoint } from '../api';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

const COLORS = [
  '#e94560', '#4ecca3', '#f5a623', '#6c5ce7',
  '#00cec9', '#fd79a8', '#a29bfe', '#55efc4',
];

function formatLabel(timestamp: string): string {
  return new Date(timestamp).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  scales: {
    y: {
      min: 0,
      max: 1,
      ticks: { color: '#8892a4' },
      grid: { color: '#0f346030' },
    },
    x: {
      ticks: { color: '#8892a4', maxRotation: 45 },
      grid: { display: false as const },
    },
  },
  plugins: {
    legend: {
      labels: { color: '#e0e0e0', usePointStyle: true, pointStyle: 'circle' as const },
    },
    tooltip: {
      backgroundColor: '#16213e',
      borderColor: '#0f3460',
      borderWidth: 1,
    },
  },
};

interface ScoreChartProps {
  mode: 'average' | 'breakdown';
  data?: ChartPoint[];
  averageData?: AverageChartPoint[];
}

export function ScoreChart({ mode, data, averageData }: ScoreChartProps) {
  if (mode === 'average') {
    if (!averageData?.length) return <div className="loading">No data</div>;

    const labels = averageData.map(d => formatLabel(d.timestamp));
    const chartData = {
      labels,
      datasets: [{
        label: 'Average Score',
        data: averageData.map(d => d.score),
        borderColor: COLORS[0],
        backgroundColor: COLORS[0] + '20',
        tension: 0.3,
        pointRadius: 4,
        pointHoverRadius: 6,
      }],
    };

    return (
      <div className="chart-container" style={{ height: 400 }}>
        <Line data={chartData} options={chartOptions} />
      </div>
    );
  }

  if (!data?.length) return <div className="loading">No data</div>;

  const rules = Object.keys(data[0].scores);
  const labels = data.map(d => formatLabel(d.timestamp));

  const chartData = {
    labels,
    datasets: rules.map((rule, i) => ({
      label: rule,
      data: data.map(d => d.scores[rule] ?? null),
      borderColor: COLORS[i % COLORS.length],
      backgroundColor: COLORS[i % COLORS.length] + '20',
      tension: 0.3,
      pointRadius: 4,
      pointHoverRadius: 6,
    })),
  };

  return (
    <div className="chart-container" style={{ height: 400 }}>
      <Line data={chartData} options={chartOptions} />
    </div>
  );
}
