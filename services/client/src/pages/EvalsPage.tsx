import { useEffect, useState, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { api } from '../api';
import type { EvalRun, ChartPoint, AverageChartPoint } from '../api';
import { ScoreChart } from '../components/ScoreChart';
import { Pagination } from '../components/Pagination';
import { makeRowClickable } from '../utils/a11y';

type ChartMode = 'average' | 'breakdown';

export function EvalsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const category = searchParams.get('category') || 'rules';
  const subcategory = searchParams.get('subcategory') || '';
  const scenario = searchParams.get('scenario') || '';
  const model = searchParams.get('model') || '';

  const setFilter = useCallback((key: string, value: string, clearKeys?: string[]) => {
    setSearchParams(prev => {
      if (value) prev.set(key, value);
      else prev.delete(key);
      for (const k of clearKeys || []) prev.delete(k);
      return prev;
    });
  }, [setSearchParams]);

  const [categories, setCategories] = useState<string[]>([]);
  const [subcategories, setSubcategories] = useState<string[]>([]);

  const [chartMode, setChartMode] = useState<ChartMode>('average');
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [averageData, setAverageData] = useState<AverageChartPoint[]>([]);

  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(10);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.evals.categories().then(setCategories).catch(() => setCategories([]));
  }, []);

  useEffect(() => {
    const params: Record<string, string> = {};
    if (category) params.eval_type = category;
    api.evals.subcategories(params).then(setSubcategories).catch(() => setSubcategories([]));
  }, [category]);

  const buildParams = useCallback((): Record<string, string> => {
    const params: Record<string, string> = {};
    if (category) params.eval_type = category;
    if (subcategory) params.subcategory = subcategory;
    if (scenario) params.scenario = scenario;
    if (model) params.model = model;
    return params;
  }, [category, subcategory, scenario, model]);

  const loadData = useCallback(() => {
    setLoading(true);
    const params = buildParams();

    const listParams = { ...params, limit: String(limit), offset: String(offset) };
    api.evals.list(listParams).then(res => {
      setRuns(res.items);
      setTotal(res.total);
    }).finally(() => setLoading(false));

    if (chartMode === 'average') {
      api.evals.chartAverage(params).then(setAverageData);
    } else {
      api.evals.chart(params).then(setChartData);
    }
  }, [buildParams, chartMode, limit, offset]);

  useEffect(() => { loadData(); }, [loadData]);

  useEffect(() => {
    setOffset(0);
  }, [scenario, model]);

  const scenarios = [...new Set(runs.map(r => r.scenario))];
  const models = [...new Set(runs.map(r => r.test_model))];

  return (
    <div>
      <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 16 }}>Results</h2>

      <div className="filters">
        <select
          value={category}
          onChange={e => setFilter('category', e.target.value, ['subcategory', 'scenario', 'model'])}
        >
          {categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={subcategory} onChange={e => setFilter('subcategory', e.target.value)}>
          <option value="">All subcategories</option>
          {subcategories.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={scenario} onChange={e => setFilter('scenario', e.target.value)}>
          <option value="">All scenarios</option>
          {scenarios.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={model} onChange={e => setFilter('model', e.target.value)}>
          <option value="">All models</option>
          {models.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>

      <div className="sub-tabs">
        <button
          className={chartMode === 'average' ? 'active' : ''}
          onClick={() => setChartMode('average')}
        >
          Average
        </button>
        {runs.some(r => (r.score_count ?? 0) > 1) && (
          <button
            className={chartMode === 'breakdown' ? 'active' : ''}
            onClick={() => setChartMode('breakdown')}
          >
            Breakdown
          </button>
        )}
      </div>

      <ScoreChart
        mode={chartMode}
        data={chartData}
        averageData={averageData}
      />

      {loading && <div className="loading">Loading...</div>}

      {!loading && (
        <>
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Category</th>
                <th>Scenario</th>
                <th>Model</th>
                <th>Threshold</th>
                <th>Scores</th>
              </tr>
            </thead>
            <tbody>
              {runs.map(run => (
                <tr key={run.id} {...makeRowClickable(() => navigate(`/evals/${run.id}`))} style={{ cursor: 'pointer' }}>
                  <td>{new Date(run.timestamp).toLocaleString()}</td>
                  <td><span className="tag">{run.eval_type}{run.subcategory ? ` / ${run.subcategory}` : ''}</span></td>
                  <td>{run.scenario}</td>
                  <td>{run.test_model}</td>
                  <td>{run.threshold}</td>
                  <td>
                    <span
                      className={`score-badge ${(run.score_avg ?? 0) >= run.threshold ? 'pass' : 'fail'}`}
                    >
                      {(run.score_avg ?? 0).toFixed(1)} ({run.score_count ?? 0} rules)
                    </span>
                  </td>
                </tr>
              ))}
              {runs.length === 0 && (
                <tr><td colSpan={6} className="loading">No eval runs found</td></tr>
              )}
            </tbody>
          </table>

          <Pagination
            total={total}
            limit={limit}
            offset={offset}
            onPageChange={setOffset}
            onLimitChange={newLimit => { setLimit(newLimit); setOffset(0); }}
          />
        </>
      )}
    </div>
  );
}
