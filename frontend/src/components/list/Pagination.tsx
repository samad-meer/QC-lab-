import type { ListState } from "../../useList";
import { PAGE_SIZES } from "../../useList";

/** Where you are in a list, and the way through it. */
export default function Pagination<T>({ list }: { list: ListState<T> }) {
  const { count, page, pages, pageSize, loading, setPage, setPageSize } = list;
  if (count === 0) return null;
  const first = (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, count);

  return (
    <nav className="pager" aria-label="Pages of this list">
      <span className="hint">Showing {first}–{last} of {count}</span>
      <div className="spacer" />
      {count > PAGE_SIZES[0] && (
        <label className="pager-size">
          Rows per page
          <select value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}>
            {PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </label>
      )}
      {pages > 1 && (
        <div className="actions-bar">
          <button className="ghost small pager-end" disabled={page <= 1 || loading} onClick={() => setPage(1)}
            aria-label="First page" title="First page">«</button>
          <button className="ghost small" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)}>
            ← Previous
          </button>
          <span className="pager-where">Page {page} of {pages}</span>
          <button className="ghost small" disabled={page >= pages || loading} onClick={() => setPage(page + 1)}>
            Next →
          </button>
          <button className="ghost small pager-end" disabled={page >= pages || loading} onClick={() => setPage(pages)}
            aria-label="Last page" title="Last page">»</button>
        </div>
      )}
    </nav>
  );
}
