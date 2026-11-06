import { ScrollableTable } from '../components/ScrollableTable';
import { SortableHeader } from '../components/table/SortableHeader';
import { useLocalTableSort } from '../hooks/useLocalTableSort';
import { COST_SORT_COLUMNS, USAGE_SORT_COLUMNS } from '../utils/costSorting';
import './costSorting.css';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { CostResponse } from '../types/costs';
import { usePolling } from '../hooks/usePolling';

function money(value: string, currency: string, precision = 2) {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    maximumFractionDigits: precision,
  }).format(Number(value));
}

function ReportTable({
  title,
  rows,
  currency,
  precision = 2,
}: {
  title: string;
  rows: { label: string; amount: string; unit?: string }[];
  currency?: string;
  precision?: number;
}) {
  const columns = currency ? COST_SORT_COLUMNS : USAGE_SORT_COLUMNS;
  const { items, sort, setSort } = useLocalTableSort(rows, columns);
  return (
    <section className="card cost-table-card" aria-label={title}>
      <h3>{title}</h3>
      <ScrollableTable label={`${title} table`} className="cost-sorting-table">
        <thead>
          <tr>
            <SortableHeader sort={sort} column={columns.label} onSort={setSort}>
              {title === 'Daily costs'
                ? 'Billing day (UTC)'
                : currency
                  ? 'Service'
                  : 'Metric'}
            </SortableHeader>
            <SortableHeader
              sort={sort}
              column={columns.amount}
              onSort={setSort}
              title={
                currency
                  ? undefined
                  : 'Groups units, then orders exact quantities within each unit'
              }
            >
              {currency ? 'Cost' : 'Observed amount'}
            </SortableHeader>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr key={row.label}>
              <td>{row.label}</td>
              <td>
                {currency
                  ? money(row.amount, currency, precision)
                  : row.amount === 'Unavailable'
                    ? 'Unavailable'
                    : `${row.amount}${row.unit ? ' ' + row.unit : ''}`}
              </td>
            </tr>
          ))}
        </tbody>
      </ScrollableTable>
    </section>
  );
}

export function CostsPage() {
  const [provider, setProvider] = useState<'aws' | 'pinecone'>('aws');
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
        {(['aws', 'pinecone'] as const).map((value) => (
          <button
            key={value}
            className={`btn${provider === value ? ' btn-primary' : ''}`}
            aria-pressed={provider === value}
            onClick={() => setProvider(value)}
          >
            {value === 'aws' ? 'AWS' : 'Pinecone'}
          </button>
        ))}
      </div>
      <p>
        <strong>This month</strong>
      </p>
      <p className="text-muted">
        Billing dates use UTC; update times use your local time.
      </p>
      <CostProvider key={provider} provider={provider} />
    </div>
  );
}

function pricingLink(value?: string | null) {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return ['http:', 'https:'].includes(parsed.protocol) &&
      !parsed.username &&
      !parsed.password
      ? value
      : null;
  } catch {
    return null;
  }
}

function CostProvider({ provider }: { provider: 'aws' | 'pinecone' }) {
  const [data, setData] = useState<CostResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const request = useRef(0);
  const load = useCallback(async () => {
    const sequence = ++request.current;
    try {
      const result = await api.costs.get(provider);
      if (result.report && result.report.provider !== provider)
        throw new Error(
          'Cost report provider does not match the selected view.',
        );
      if (sequence !== request.current) return;
      setData(result);
      setFailed(false);
    } catch {
      if (sequence === request.current) setFailed(true);
    } finally {
      if (sequence === request.current) setLoading(false);
    }
  }, [provider]);
  useEffect(() => {
    void load();
    return () => {
      request.current += 1;
    };
  }, [load]);
  usePolling(load);
  const report = data?.report;
  const precision = provider === 'pinecone' ? 6 : 2;
  const source = pricingLink(report?.pricing_source);
  const stale = data?.state === 'stale' || (failed && report);

  return (
    <div>
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
          {provider === 'pinecone' && !data?.error && !failed
            ? 'Showing the last observed snapshot while waiting for its next update.'
            : 'Showing the last successful report; the latest refresh failed.'}
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
              {provider === 'pinecone'
                ? 'Observed usage estimate'
                : report.estimated
                  ? 'Estimated charges'
                  : 'Reported charges'}
            </h3>
            <p>
              {report.total === null ? (
                'Cost unavailable for this period'
              ) : (
                <strong style={{ fontSize: '2rem' }}>
                  {money(report.total, report.currency, precision)}
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
            {report.coverage_start && (
              <p>
                Observed since:{' '}
                <time dateTime={report.coverage_start}>
                  {new Date(report.coverage_start).toLocaleString()}
                </time>
              </p>
            )}
            {source && (
              <p>
                <a href={source} target="_blank" rel="noreferrer">
                  Configured pricing source
                </a>
                {report.pricing_as_of
                  ? ` (rate reference date: ${report.pricing_as_of})`
                  : ''}
              </p>
            )}
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
          {provider === 'pinecone' && report.usage.length > 0 && (
            <ReportTable title="Observed usage" rows={report.usage} />
          )}
          {report.breakdown.length > 0 && (
            <ReportTable
              title="Costs by service"
              rows={report.breakdown}
              currency={report.currency}
              precision={precision}
            />
          )}
          {report.daily.length > 0 && (
            <ReportTable
              title="Daily costs"
              rows={report.daily}
              currency={report.currency}
              precision={precision}
            />
          )}
        </>
      )}
      <p>
        <a
          href={
            provider === 'aws'
              ? 'https://console.aws.amazon.com/costmanagement/home#/cost-explorer'
              : 'https://app.pinecone.io/'
          }
          target="_blank"
          rel="noreferrer"
        >
          {provider === 'aws'
            ? 'Open AWS Cost Explorer'
            : 'Open Pinecone console'}
        </a>
      </p>
    </div>
  );
}
