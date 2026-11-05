import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { CostResponse } from '../types/costs';
import { usePolling } from '../hooks/usePolling';

function money(value: string, currency: string) {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function CostTable({
  title,
  rows,
  currency,
}: {
  title: string;
  rows: { label: string; amount: string }[];
  currency: string;
}) {
  return (
    <section className="card" aria-label={title}>
      <h3>{title}</h3>
      <div className="table-container">
        <table className="table">
          <thead>
            <tr>
              <th>
                {title === 'Daily costs' ? 'Billing day (UTC)' : 'Service'}
              </th>
              <th>Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <td>{row.label}</td>
                <td>{money(row.amount, currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function CostsPage() {
  const [data, setData] = useState<CostResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const request = useRef(0);
  const load = useCallback(async () => {
    const sequence = ++request.current;
    try {
      const result = await api.costs.get('aws');
      if (sequence !== request.current) return;
      setData(result);
      setFailed(false);
    } catch {
      if (sequence === request.current) setFailed(true);
    } finally {
      if (sequence === request.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
    return () => {
      request.current += 1;
    };
  }, [load]);
  usePolling(load);
  const report = data?.report;
  const stale = data?.state === 'stale' || (failed && report);

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">Costs</h2>
      </div>
      <div
        className="filter-status-group"
        role="group"
        aria-label="Cost provider"
      >
        <button className="btn btn-primary" aria-pressed="true">
          AWS
        </button>
      </div>
      <p>
        <strong>This month</strong>
      </p>
      <p className="text-muted">
        Billing dates use UTC; update times use your local time.
      </p>
      {loading && <div className="loading">Loading costs…</div>}
      {failed && (
        <div role="alert" className="card">
          Could not load costs.{' '}
          <button className="btn" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}
      {stale && (
        <p role="status">
          Showing the last successful report; the latest refresh failed.
        </p>
      )}
      {data?.error && <p role="alert">{data.error.message}</p>}
      {data?.message && <p className="card">{data.message}</p>}
      {data?.state === 'pending' && (
        <p role="status">The first cost report is being collected.</p>
      )}
      {report && (
        <>
          <section className="card" aria-label="Cost summary">
            <h3>
              {report.estimated ? 'Estimated charges' : 'Reported charges'}
            </h3>
            <p>
              {report.total === null ? (
                'Cost unavailable for this period'
              ) : (
                <strong style={{ fontSize: '2rem' }}>
                  {money(report.total, report.currency)}
                </strong>
              )}
            </p>
            <p>{report.scope}</p>
            <p>
              {report.period_start} through {report.period_end} (end exclusive,
              UTC)
            </p>
            <p>Cost basis: {report.cost_basis}</p>
            <p>Last updated: {new Date(report.fetched_at).toLocaleString()}</p>
            {report.data_through && (
              <p>Latest provider billing day: {report.data_through} (UTC)</p>
            )}
            {data.next_refresh_at && (
              <p>
                Next provider refresh:{' '}
                {new Date(data.next_refresh_at).toLocaleString()}
              </p>
            )}
            {report.notes.map((note) => (
              <p className="text-muted" key={note}>
                {note}
              </p>
            ))}
          </section>
          {report.breakdown.length > 0 && (
            <CostTable
              title="Costs by service"
              rows={report.breakdown}
              currency={report.currency}
            />
          )}
          {report.daily.length > 0 && (
            <CostTable
              title="Daily costs"
              rows={report.daily}
              currency={report.currency}
            />
          )}
        </>
      )}
      <p>
        <a
          href="https://console.aws.amazon.com/costmanagement/home#/cost-explorer"
          target="_blank"
          rel="noreferrer"
        >
          Open AWS Cost Explorer
        </a>
      </p>
    </div>
  );
}
