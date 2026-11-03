import { useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { EvalRun, ChartPoint, AverageChartPoint } from '../api';
import { ScoreChart } from '../components/ScoreChart';
import { ScrollableTable } from '../components/ScrollableTable';
import { Pagination } from '../components/Pagination';
import { FilterBar } from '../components/FilterBar';
import { useApiRead } from '../hooks/useApiRead';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { usePagination } from '../hooks/usePagination';
import { RESULT_SORT_OPTIONS } from '../constants';
import { useViewPreferences } from '../hooks/useViewPreferences';
import { parseViewField } from '../utils/viewPreferences';
import { makeRowClickable } from '../utils/a11y';

type ChartMode = 'average' | 'breakdown';
type ChartData = { mode: 'average'; points: AverageChartPoint[] } | { mode: 'breakdown'; points: ChartPoint[] };

export function EvalsPage() {
  const navigate = useNavigate();
  const preferences = useViewPreferences('results');
  const { category, subcategory, scenario, model, q: query, sort } = preferences.values;
  const debouncedQuery = useDebouncedValue(query);

  const [chartMode, setChartMode] = useState<ChartMode>('average');
  const params = useMemo((): Record<string, string> => {
    const params: Record<string, string> = {};
    if (category) params.eval_type = category;
    if (subcategory) params.subcategory = subcategory;
    if (scenario) params.scenario = scenario;
    if (model) params.model = model;
    if (debouncedQuery) params.q = debouncedQuery;
    return params;
  }, [category, subcategory, scenario, model, debouncedQuery]);
  const { items: runs, total, loading, error, limit, offset, setLimit, setOffset, refresh } = usePagination<EvalRun>(
    (l, o) => api.evals.list({ ...params, sort, limit: String(l), offset: String(o) }),
    [category, subcategory, scenario, model, debouncedQuery, sort], 10, { ...preferences.pagination, enabled: query === debouncedQuery },
  );
  const categories = useApiRead(useCallback(() => api.evals.categories(), []));
  const subcategories = useApiRead(useCallback(() => api.evals.subcategories(category ? { eval_type: category } : {}), [category]));
  const facetParams = useMemo(() => {
    const values = { ...params };
    delete values.scenario;
    delete values.model;
    return values;
  }, [params]);
  const facets = useApiRead(useCallback(() => api.evals.facets(facetParams), [facetParams]), { enabled: query === debouncedQuery });
  const chart = useApiRead<ChartData>(useCallback(async (): Promise<ChartData> => chartMode === 'average'
    ? { mode: 'average', points: await api.evals.chartAverage(params) }
    : { mode: 'breakdown', points: await api.evals.chart(params) }, [chartMode, params]), { enabled: query === debouncedQuery });
  const scenarios = [...new Set([...(facets.data?.scenarios || []), ...(scenario ? [scenario] : [])])];
  const models = [...new Set([...(facets.data?.models || []), ...(model ? [model] : [])])];

  return (
    <div>
      <h2 className="page-title" style={{ marginBottom: 16 }}>Results</h2>

      <FilterBar nameValue={query} onNameChange={value => preferences.setField('q', value)} onReset={preferences.reset} namePlaceholder="Search results...">
        <label><span className="form-label">Category</span>
        <select
          aria-label="Result category"
          value={category}
          onChange={e => preferences.setFields({ category: e.target.value, subcategory: '', scenario: '', model: '' })}
        >
          <option value="">All categories</option>
          {[...new Set([...(categories.data || []), ...(category ? [category] : [])])].map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        </label>
        <label><span className="form-label">Subcategory</span>
        <select aria-label="Result subcategory" value={subcategory} onChange={e => preferences.setFields({ subcategory: e.target.value, scenario: '', model: '' })}>
          <option value="">All subcategories</option>
          {[...new Set([...(subcategories.data || []), ...(subcategory ? [subcategory] : [])])].map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        </label>
        <label><span className="form-label">Scenario</span>
        <select aria-label="Result scenario" value={scenario} onChange={e => preferences.setField('scenario', e.target.value)}>
          <option value="">All scenarios</option>
          {scenarios.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        </label>
        <label><span className="form-label">Model</span>
        <select aria-label="Result model" value={model} onChange={e => preferences.setField('model', e.target.value)}>
          <option value="">All models</option>
          {models.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        </label>
        <label><span className="form-label">Sort results</span>
        <select aria-label="Sort results" value={sort} onChange={e => preferences.setField('sort', parseViewField('results', 'sort', e.target.value))}>
          {RESULT_SORT_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        </label>
      </FilterBar>
      {(categories.error || subcategories.error || facets.error) && <p role="alert">Could not load result filter options.</p>}

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

      {chart.error && <p role="alert">Could not load the chart. <button className="btn btn-sm" onClick={() => chart.refresh()}>Retry chart</button></p>}
      {chart.loading && <div className="loading" role="status">Loading chart...</div>}
      {!chart.loading && !chart.error && <ScoreChart
        mode={chartMode}
        data={chart.data?.mode === 'breakdown' ? chart.data.points : []}
        averageData={chart.data?.mode === 'average' ? chart.data.points : []}
      />}

      {error && <p role="alert">Could not load results. <button className="btn btn-sm" onClick={() => refresh()}>Retry</button></p>}
      {loading && <div className="loading">Loading...</div>}

      {!loading && !error && (
        <>
          <ScrollableTable label="Results list" className="results-list-table" empty={runs.length === 0}>
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
              {!error && runs.length === 0 && (
                <tr><td colSpan={6} className="loading">No eval runs found</td></tr>
              )}
            </tbody>
          </ScrollableTable>

        </>
      )}
      {!error && <Pagination total={total} limit={limit} offset={offset} onPageChange={setOffset}
        onLimitChange={newLimit => { setLimit(newLimit); setOffset(0); }} disabled={loading} />}
    </div>
  );
}
