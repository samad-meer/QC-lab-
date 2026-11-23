import type { ReactNode } from "react";
import { useAuth } from "../../auth";
import type { ListState } from "../../useList";
import { EmptyState, Message, TableSkeleton } from "../Feedback";
import ExportButtons from "../reports/ExportButtons";
import Pagination from "./Pagination";

/**
 * A list in its card: heading, filters, and every state a list can be in —
 * loading, failed, empty or filled — with its pager. A page says only what
 * is its own: the words, the filters, and how one page of rows is drawn.
 */
export default function ListCard<T>({
  title,
  hint,
  actions,
  filters,
  list,
  failure,
  emptyTitle = "Nothing here right now",
  emptySub,
  skeletonRows,
  exportable = false,
  children,
}: {
  title: string;
  hint?: ReactNode;
  /** Buttons at the right of the heading. */
  actions?: ReactNode;
  filters?: ReactNode;
  list: ListState<T>;
  /** Leads the error, e.g. "Could not load samples". */
  failure: string;
  emptyTitle?: string;
  emptySub?: string;
  skeletonRows?: number;
  /** Offer the whole list, under its filters, as Excel or PDF — to those who may export. */
  exportable?: boolean;
  children: (rows: T[]) => ReactNode;
}) {
  const { can } = useAuth();
  const { rows, error, loaded, loading } = list;
  return (
    <div className="card">
      <div className="card-head">
        <h2>{title}</h2>
        {hint && <span className="hint">{hint}</span>}
        <div className="spacer" />
        {actions}
        {exportable && can("report.export") && (
          <ExportButtons url={list.exportUrl} formats={["xlsx", "pdf"]} what="list"
            disabled={!loaded || Boolean(error) || list.count === 0} />
        )}
      </div>
      {filters && <div className="list-filters">{filters}</div>}
      <div className={`card-body flush ${loaded && loading ? "list-busy" : ""}`} aria-busy={loading}>
        {error ? (
          <div style={{ padding: 18 }}>
            <Message kind="error">{failure} — {error}</Message>
          </div>
        ) : !loaded ? (
          <TableSkeleton rows={skeletonRows} />
        ) : rows.length === 0 ? (
          <EmptyState title={emptyTitle} sub={emptySub} />
        ) : (
          children(rows)
        )}
      </div>
      {!error && <Pagination list={list} />}
    </div>
  );
}
