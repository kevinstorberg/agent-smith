interface PaginationProps {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (offset: number) => void;
  onLimitChange: (limit: number) => void;
}

const LIMIT_OPTIONS = [10, 25, 50];

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

export function Pagination({ total, limit, offset, onPageChange, onLimitChange }: PaginationProps) {
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
    <div className="pagination">
      <span className="pagination-info">
        Showing {showStart}&ndash;{showEnd} of {total}
      </span>
      <div className="pagination-controls">
        <button
          className="pagination-btn"
          disabled={currentPage <= 1}
          onClick={() => goToPage(currentPage - 1)}
        >
          Previous
        </button>
        {pages.map((p, i) =>
          p === 'ellipsis' ? (
            <span key={`e${i}`} className="pagination-ellipsis">&hellip;</span>
          ) : (
            <button
              key={p}
              className={`pagination-btn${p === currentPage ? ' active' : ''}`}
              onClick={() => goToPage(p)}
            >
              {p}
            </button>
          )
        )}
        <button
          className="pagination-btn"
          disabled={currentPage >= totalPages}
          onClick={() => goToPage(currentPage + 1)}
        >
          Next
        </button>
        <select
          className="pagination-select"
          value={limit}
          onChange={e => onLimitChange(Number(e.target.value))}
        >
          {LIMIT_OPTIONS.map(n => (
            <option key={n} value={n}>{n} / page</option>
          ))}
        </select>
      </div>
    </div>
  );
}
