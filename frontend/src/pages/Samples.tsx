import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../api";
import DueChip from "../components/DueChip";
import { EmptyState } from "../components/Feedback";
import LineIcon from "../components/LineIcon";
import PersonChip from "../components/PersonChip";
import ListCard from "../components/list/ListCard";
import SampleFilters, { useSampleFilters } from "../components/SampleFilters";
import SampleTable from "../components/SampleTable";
import type { Page, SampleListItem, SampleStatus, Summary } from "../types";
import { useList, useUrlFilters } from "../useList";

const FILTERS: { key: SampleStatus | "ALL"; label: string }[] = [
  { key: "ALL", label: "All" },
  { key: "RECEIVED", label: "Received" },
  { key: "IN_TESTING", label: "In testing" },
  { key: "IN_REVIEW", label: "In review" },
  { key: "APPROVED", label: "Approved" },
];

/** The board: one column per status, left to right as a sample moves through the lab. */
const COLUMNS: { key: SampleStatus; title: string; hint: string; color: string }[] = [
  { key: "RECEIVED", title: "Received", hint: "Receipt checks, or testing not started", color: "var(--warn)" },
  { key: "IN_TESTING", title: "In testing", hint: "With the analyst", color: "var(--chart-1)" },
  { key: "IN_REVIEW", title: "In review", hint: "Waiting for a signature", color: "var(--chart-2)" },
  { key: "APPROVED", title: "Approved", hint: "Certificate in force", color: "var(--pass)" },
  { key: "REJECTED", title: "Rejected", hint: "Did not pass", color: "var(--fail)" },
];
const PER_COLUMN = 12;
const FINISHED: SampleStatus[] = ["APPROVED", "REJECTED", "CANCELLED"];

type View = "list" | "board";
const VIEW_KEY = "qclab.samples.view";

function savedView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === "board" ? "board" : "list";
  } catch {
    return "list";
  }
}

function SampleCard({ s }: { s: SampleListItem }) {
  return (
    <article className="tk-card sb-card">
      <div className="sb-card-top">
        <Link to={`/samples/${s.id}`} className="task-no">{s.sample_no}</Link>
        <span className="tag soft">{s.section_code}</span>
      </div>
      <div className="sb-card-product">{s.product_name}</div>
      <div className="cell-sub">{s.batch_label}</div>
      <div className="sb-card-person">
        <PersonChip id={s.assigned_analyst_id} name={s.analyst_name} role="Analyst" />
      </div>
      <div className="sb-card-meta">
        <DueChip due={s.due_date} done={FINISHED.includes(s.status)} />
        {s.has_failures && <span className="badge fail">Failed test</span>}
      </div>
      {s.status !== "APPROVED" && <div className="sb-card-state">{s.status_label}</div>}
      {s.can_sign && (
        <div className="tk-card-actions">
          <Link to={`/samples/${s.id}/review`} className="btn-link">{s.my_turn ? "Review and sign →" : "Review →"}</Link>
        </div>
      )}
    </article>
  );
}

/** One status: its first samples under the page's filters, and more on asking. */
function StatusColumn({ col, query, onOpenList }: {
  col: (typeof COLUMNS)[number];
  query: Record<string, string>;
  onOpenList: (status: SampleStatus) => void;
}) {
  const [rows, setRows] = useState<SampleListItem[] | null>(null);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const key = JSON.stringify(query);

  const fetchPage = useCallback(async (n: number) => {
    const params = new URLSearchParams({ ...query, status: col.key, page: String(n), page_size: String(PER_COLUMN) });
    return apiGet<Page<SampleListItem>>(`/api/samples/?${params.toString()}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, col.key]);

  useEffect(() => {
    let live = true;
    setRows(null);
    fetchPage(1)
      .then((p) => {
        if (!live) return;
        setRows(p.results);
        setCount(p.count);
        setPage(1);
        setError("");
      })
      .catch((err) => live && setError(err instanceof Error ? err.message : "Could not load."));
    return () => {
      live = false;
    };
  }, [fetchPage]);

  const more = async () => {
    setBusy(true);
    try {
      const p = await fetchPage(page + 1);
      setRows((now) => [...(now ?? []), ...p.results]);
      setPage(page + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load more.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="tk-col sb-col" aria-label={col.title} style={{ "--sb-color": col.color } as CSSProperties}>
      <div className="tk-col-head">
        <b>{col.title}</b>
        <span className="tk-col-count">{rows === null ? "…" : count}</span>
        <small>{col.hint}</small>
      </div>
      {error && <p className="tk-col-empty">{error}</p>}
      {rows === null ? (
        [0, 1, 2].map((i) => <div key={i} className="tk-card sk sb-card-sk" />)
      ) : rows.length === 0 ? (
        <p className="tk-col-empty">Nothing here</p>
      ) : (
        <>
          {rows.map((s) => <SampleCard key={s.id} s={s} />)}
          {rows.length < count && (
            <div className="sb-more">
              <button type="button" className="ghost small" disabled={busy} onClick={() => void more()}>
                {busy ? "Loading…" : `Show more (${count - rows.length})`}
              </button>
              <button type="button" className="link-btn" onClick={() => onOpenList(col.key)}>All in the list</button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

export default function Samples() {
  // The dashboard links straight to one status: /samples?status=IN_REVIEW
  const { params, setFilters } = useUrlFilters();
  const status = FILTERS.find((f) => f.key === params.get("status"))?.key ?? "ALL";
  const filters = useSampleFilters();
  const { range } = filters;
  const list = useList<SampleListItem>("/api/samples/", { query: { ...filters.query, status } });
  const [summary, setSummary] = useState<Summary | null>(null);
  const [view, setView] = useState<View>(savedView);

  useEffect(() => {
    apiGet<Summary>(`/api/summary/?${range.search}`).then(setSummary).catch(() => undefined);
  }, [range.search, list.data]);

  const choose = (next: View) => {
    setView(next);
    try {
      localStorage.setItem(VIEW_KEY, next);
    } catch {
      /* the choice just isn't remembered */
    }
  };

  const statusButtons = (
    <div className="actions-bar">
      {FILTERS.map((f) => (
        <button
          key={f.key}
          className={status === f.key ? "primary small" : "subtle small"}
          onClick={() => setFilters({ status: f.key === "ALL" ? "" : f.key })}
        >
          {f.label}
        </button>
      ))}
    </div>
  );

  // A status chosen above narrows the board to its column; Rejected shows only when there are some.
  const columns = COLUMNS.filter((c) => (status === "ALL" ? c.key !== "REJECTED" || (summary?.by_status.REJECTED ?? 0) > 0 : c.key === status));

  return (
    <>
      <div className="page-head page-head-split">
        <div>
          <h1>All samples</h1>
          <p className="sub">The whole pipeline, newest first. Select a sample to open it.</p>
        </div>
        <div className="page-head-aside">
          <div className="seg" role="group" aria-label="View">
            <button type="button" className={view === "list" ? "on" : ""} aria-pressed={view === "list"} onClick={() => choose("list")}>
              <LineIcon name="list" size={15} /> List
            </button>
            <button type="button" className={view === "board" ? "on" : ""} aria-pressed={view === "board"} onClick={() => choose("board")}>
              <LineIcon name="board" size={15} /> Board
            </button>
          </div>
        </div>
      </div>

      {summary && (
        <div className="stat-row">
          <div className="stat">
            <div className="stat-label">In the lab</div>
            <div className="stat-value">{summary.total}</div>
          </div>
          <div className="stat">
            <div className="stat-label">In testing</div>
            <div className="stat-value">{summary.by_status.RECEIVED + summary.by_status.IN_TESTING}</div>
          </div>
          <div className="stat">
            <div className="stat-label">In review</div>
            <div className="stat-value">{summary.by_status.IN_REVIEW}</div>
          </div>
          <div className={`stat ${summary.overdue > 0 ? "alert" : ""}`}>
            <div className="stat-label">Past due</div>
            <div className="stat-value">{summary.overdue}</div>
          </div>
        </div>
      )}

      {view === "list" ? (
        <ListCard
          title="Samples"
          exportable
          list={list}
          failure="Could not load samples"
          emptyTitle="No samples match these filters"
          emptySub="Try a different status or a wider date range."
          actions={statusButtons}
          filters={<SampleFilters filters={filters} />}
        >
          {(rows) => <SampleTable samples={rows} />}
        </ListCard>
      ) : (
        <>
          <div className="card sb-board-head">
            <div className="card-head">
              <h2>Samples</h2>
              <span className="hint">By status, newest first in each column</span>
              <div className="spacer" />
              {statusButtons}
            </div>
            <div className="list-filters"><SampleFilters filters={filters} /></div>
          </div>
          {columns.length === 0 ? (
            <div className="card"><EmptyState title="No samples match these filters" sub="Try a different status or a wider date range." /></div>
          ) : (
            <div className="tk-board" style={{ "--tk-cols": columns.length } as CSSProperties}>
              {columns.map((col) => (
                <StatusColumn key={col.key} col={col} query={filters.query}
                  onOpenList={(s) => {
                    setFilters({ status: s });
                    choose("list");
                  }} />
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}
