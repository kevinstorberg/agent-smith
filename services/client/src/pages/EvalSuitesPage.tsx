import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { api } from '../api';
import type { EvalSuite } from '../api';
import { EnabledToggleCell, DateCell } from '../components/table';
import { ScrollableTable } from '../components/ScrollableTable';
import { FilterBar } from '../components/FilterBar';
import { Pagination } from '../components/Pagination';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { makeRowClickable } from '../utils/a11y';
import { EVAL_SUITE_SORT_OPTIONS } from '../constants';
import { useViewPreferences } from '../hooks/useViewPreferences';
import { parseViewField } from '../utils/viewPreferences';

export function EvalSuitesPage() {
  const navigate = useNavigate();
  const preferences = useViewPreferences('evalSuites');
  const { q: query, enabled, sort } = preferences.values;
  const [mutationError, setMutationError] = useState(false);
  const [togglePending, setTogglePending] = useState(false);
  const writing = useRef(false);
  const debouncedQuery = useDebouncedValue(query);
  const {
    items: suites,
    total,
    loading,
    error,
    limit,
    offset,
    setLimit,
    setOffset,
    refresh,
  } = usePagination<EvalSuite>(
    (l, o) =>
      api.evalConfigs.suites.list({
        enabled_only: 'false',
        limit: String(l),
        offset: String(o),
        sort,
        ...(debouncedQuery ? { q: debouncedQuery } : {}),
        ...(enabled ? { enabled } : {}),
      }),
    [debouncedQuery, enabled, sort],
    10,
    { ...preferences.pagination, enabled: debouncedQuery === query },
  );
  const latestRefresh = useRef(refresh);
  const mounted = useRef(false);
  useEffect(() => {
    latestRefresh.current = refresh;
  }, [refresh]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  usePolling(() => refresh({ showLoading: false }), {
    enabled: !loading && !togglePending && debouncedQuery === query,
  });

  const toggleEnabled = async (suite: EvalSuite) => {
    if (writing.current) return;
    writing.current = true;
    setTogglePending(true);
    setMutationError(false);
    try {
      await api.evalConfigs.suites.update(suite.id, {
        enabled: !suite.enabled,
      });
      if (mounted.current) await latestRefresh.current({ showLoading: false });
    } catch {
      if (mounted.current) setMutationError(true);
    } finally {
      writing.current = false;
      if (mounted.current) setTogglePending(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">Evals</h2>
        <button
          className="btn btn-primary"
          onClick={() => navigate('/eval-configs/new')}
        >
          + New Suite
        </button>
      </div>

      <FilterBar
        nameValue={query}
        onNameChange={(value) => preferences.setField('q', value)}
        namePlaceholder="Search eval suites..."
      >
        <label>
          <span className="form-label">Enabled state</span>
          <select
            aria-label="Suite enabled state"
            value={enabled}
            onChange={(event) =>
              preferences.setField(
                'enabled',
                parseViewField('evalSuites', 'enabled', event.target.value),
              )
            }
          >
            <option value="">All enabled states</option>
            <option value="true">Enabled</option>
            <option value="false">Disabled</option>
          </select>
        </label>
        <label>
          <span className="form-label">Sort eval suites</span>
          <select
            aria-label="Sort eval suites"
            value={sort}
            onChange={(event) =>
              preferences.setField(
                'sort',
                parseViewField('evalSuites', 'sort', event.target.value),
              )
            }
          >
            {EVAL_SUITE_SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </FilterBar>
      {error && (
        <p role="alert">
          {'Could not load eval suites. '}
          <button className="btn btn-sm" onClick={() => refresh()}>
            Retry
          </button>
        </p>
      )}
      {mutationError && (
        <p role="alert">Could not change the suite. Try again.</p>
      )}
      {loading && <div className="loading">Loading...</div>}

      {!loading && !error && (
        <ScrollableTable
          label="Eval suites"
          className="suites-list-table"
          empty={suites.length === 0}
        >
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Scenarios</th>
              <th>Enabled</th>
              <th>Updated</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {suites.map((suite) => (
              <tr
                key={suite.id}
                {...makeRowClickable(() =>
                  navigate(`/eval-configs/${suite.id}`),
                )}
                style={{ cursor: 'pointer' }}
              >
                <td style={{ fontWeight: 500 }}>{suite.name}</td>
                <td>
                  <span className="tag">
                    {suite.eval_type} / {suite.subcategory}
                  </span>
                </td>
                <td>{suite.scenario_count ?? '—'}</td>
                <td>
                  <EnabledToggleCell
                    enabled={suite.enabled}
                    disabled={togglePending}
                    ariaLabel={`Enable ${suite.name}`}
                    onChange={() => toggleEnabled(suite)}
                  />
                </td>
                <td>
                  <DateCell date={suite.updated_at} />
                </td>
                <td
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => e.stopPropagation()}
                >
                  <Link
                    to={`/evals?category=${encodeURIComponent(suite.eval_type)}&subcategory=${encodeURIComponent(suite.subcategory)}`}
                    style={{
                      color: 'var(--info)',
                      cursor: 'pointer',
                      fontSize: 12,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    Results &rarr;
                  </Link>
                </td>
              </tr>
            ))}
            {!error && suites.length === 0 && (
              <tr>
                <td colSpan={6} className="loading">
                  No eval suites found
                </td>
              </tr>
            )}
          </tbody>
        </ScrollableTable>
      )}

      {!error && (
        <Pagination
          total={total}
          limit={limit}
          offset={offset}
          onPageChange={setOffset}
          onLimitChange={(value) => {
            setLimit(value);
            setOffset(0);
          }}
          disabled={loading}
        />
      )}
      <p style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 8 }}>
        {total} suite{total !== 1 ? 's' : ''}
      </p>
    </div>
  );
}
