import { useEffect, useState } from 'react';
import { api } from '../api';
import type { EvalRun, ChartPoint } from '../api';
import { ScoreChart } from '../components/ScoreChart';

export function EvalsPage() {
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [scenario, setScenario] = useState('');
  const [model, setModel] = useState('');

  const load = () => {
    const params: Record<string, string> = {};
    if (scenario) params.scenario = scenario;
    if (model) params.model = model;
    api.evals.chart(params).then(setChartData);
    api.evals.list(params).then(setRuns);
  };

  useEffect(load, [scenario, model]);

  const scenarios = [...new Set(runs.map((r) => r.scenario))];
  const models = [...new Set(runs.map((r) => r.test_model))];

  return (
    <div>
      <div className="filters">
        <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
          <option value="">All scenarios</option>
          {scenarios.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={model} onChange={(e) => setModel(e.target.value)}>
          <option value="">All models</option>
          {models.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>

      <ScoreChart data={chartData} />

      <table className="table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Scenario</th>
            <th>Model</th>
            <th>Threshold</th>
            <th>Scores</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <>
              <tr
                key={run.id}
                style={{ cursor: 'pointer' }}
                onClick={() => setExpanded(expanded === run.id ? null : run.id)}
              >
                <td>{new Date(run.timestamp).toLocaleString()}</td>
                <td>{run.scenario}</td>
                <td>{run.test_model}</td>
                <td>{run.threshold}</td>
                <td>
                  {run.results.map((r) => (
                    <span
                      key={r.rule}
                      className={`score ${r.score >= run.threshold ? 'pass' : 'fail'}`}
                      style={{ marginRight: 8 }}
                      title={r.rule}
                    >
                      {r.rule}: {r.score.toFixed(1)}
                    </span>
                  ))}
                </td>
              </tr>
              {expanded === run.id && (
                <tr key={`${run.id}-detail`}>
                  <td colSpan={5} style={{ padding: 16 }}>
                    {run.results.map((r) => (
                      <div key={r.rule} className="card" style={{ marginBottom: 8 }}>
                        <h3>
                          <span className={`score ${r.score >= run.threshold ? 'pass' : 'fail'}`}>
                            {r.score.toFixed(2)}
                          </span>{' '}
                          {r.rule}
                        </h3>
                        <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>{r.reason}</p>
                      </div>
                    ))}
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}
