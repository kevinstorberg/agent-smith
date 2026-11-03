import { useId } from 'react';
import { PAGE_LIMITS } from '../constants';

interface PaginationProps {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (offset: number) => void;
  onLimitChange?: (limit: number) => void;
  disabled?: boolean;
}

function buildPageNumbers(current: number, total: number): (number | 'ellipsis')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);

  const pages: (number | 'ellipsis')[] = [];
  pages.push(1);

  if (current > 3) pages.push('ellipsis');

  const start = Math.max(2, current - 1);
  const end = Math.min(total - 1, current + 1);
  for (let i = start; i <= end; i++) pages.push(i);

  if (current < total - 2) pages.push('ellipsis');

  pages.push(total);
  return pages;
}

export function Pagination({ total, limit, offset, onPageChange, onLimitChange, disabled = false }: PaginationProps) {
  const limitId = useId();
  if (total === 0) return null;

  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;
  const showStart = offset + 1;
  const showEnd = Math.min(offset + limit, total);

  const goToPage = (page: number) => {
    onPageChange((page - 1) * limit);
  };

  const pages = buildPageNumbers(currentPage, totalPages);

  return (
    <nav className="pagination" aria-label="Pagination">
      <div className="pagination-layout">
        <div className="pagination-summary">
          <span className="pagination-info">
            Showing {showStart}&ndash;{showEnd} of {total}
          </span>
          {onLimitChange && <label className="pagination-page-size" htmlFor={limitId}>
            <span>Rows per page</span>
            <select
              id={limitId}
              className="pagination-select"
              value={limit}
              disabled={disabled}
              onChange={e => onLimitChange(Number(e.target.value))}
            >
              {PAGE_LIMITS.map(n => (
                <option key={n} value={n}>{n} / page</option>
              ))}
            </select>
          </label>}
        </div>
        {totalPages > 1 && <div className="pagination-controls">
          <span className="pagination-position" aria-current="page">Page {currentPage} of {totalPages}</span>
          <button
            className="pagination-btn"
            type="button"
            disabled={disabled || currentPage <= 1}
            onClick={() => goToPage(currentPage - 1)}
          >
            Previous
          </button>
          <div className="pagination-pages">
            {pages.map((p, i) =>
              p === 'ellipsis' ? (
                <span key={`e${i}`} className="pagination-ellipsis">&hellip;</span>
              ) : (
                <button
                  key={p}
                  className={`pagination-btn${p === currentPage ? ' active' : ''}`}
                  type="button"
                  aria-current={p === currentPage ? 'page' : undefined}
                  disabled={disabled}
                  onClick={() => goToPage(p)}
                >
                  {p}
                </button>
              )
            )}
          </div>
          <button
            className="pagination-btn"
            type="button"
            disabled={disabled || currentPage >= totalPages}
            onClick={() => goToPage(currentPage + 1)}
          >
            Next
          </button>
        </div>}
      </div>
    </nav>
  );
}
