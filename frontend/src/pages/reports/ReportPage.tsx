import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet } from "../../api";
import { Stat } from "../../components/Charts";
import { Message, TableSkeleton } from "../../components/Feedback";
import DateRangeFilter from "../../components/list/DateRangeFilter";
import ListCard from "../../components/list/ListCard";
import TextFilter from "../../components/list/TextFilter";
import ExportButtons from "../../components/reports/ExportButtons";
import ReportCell from "../../components/reports/ReportCell";
import type { ReportColumn, ReportDefinition, ReportExtra, ReportRow } from "../../types";
import { useDateRange, useList, useUrlFilters } from "../../useList";

function SortHeader({ column, sort, onSort }: {
  column: ReportColumn;
  sort: string;
  onSort: (next: string) => void;
}) {
  const name = column.label;
  if (!column.sortable) return <th className={column.numeric ? "right" : ""}>{name}</th>;
  const ascending = sort === column.key;
  const descending = sort === `-${column.key}`;
  return (
    <th className={column.numeric ? "right" : ""} aria-sort={ascending ? "ascending" : descending ? "descending" : "none"}>
      <button type="button" className="th-sort" onClick={() => onSort(ascending ? `-${column.key}` : column.key)}>
        {name}
        <span aria-hidden="true">{ascending ? " ▲" : descending ? " ▼" : ""}</span>
      </button>
    </th>
  );
}

/** Every report but the three about one thing: the server says what it holds, this draws it. */
function ReportBody({ def }: { def: ReportDefinition }) {
  const { params, setFilters } = useUrlFilters();
  const range = useDateRange({ defaultPeriod: def.default_period, fields: def.dates });
  const sort = params.get("sort") || def.default_sort;

  const query: Record<string, string> = def.has_dates ? { ...range.query } : {};
  for (const filter of def.filters) {
    const value = params.get(filter.key);
    if (value) query[filter.key] = value;
  }
  if (params.get("sort")) query.sort = sort;

  const list = useList<ReportRow, ReportExtra>(`/api/reports/${def.key}/`, { query });
  const extra = list.data;

  return (
    <>
      <div className="breadcrumb"><Link to="/reports">Reports</Link> / {def.title}</div>
      <div className="page-head">
        <h1>{def.title}</h1>
        <p className="sub">{def.description}</p>
      </div>
      {def.note && <div style={{ marginBottom: 16 }}><Message kind="info">{def.note}</Message></div>}

      {extra && extra.summary.length > 0 && (
        <div className="stat-row fit">
          {extra.summary.map((tile) => (
            <Stat key={tile.label} label={tile.label} value={tile.value} sub={tile.sub} alert={tile.alert} />
          ))}
        </div>
      )}

      <ListCard
        title={list.loaded ? `${list.count} ${list.count === 1 ? "record" : "records"}` : "Records"}
        hint={[extra?.subject && `Report for ${extra.subject}`, extra?.period].filter(Boolean).join(" · ")}
        list={list}
        failure={`Could not load ${def.title}`}
        emptyTitle="Nothing matches"
        emptySub={def.has_dates ? "Try a wider date range or clear the filters." : "Try clearing the filters."}
        skeletonRows={6}
        actions={
          <>
            {def.action && <Link to={def.action.to} className="btn-link">{def.action.label} →</Link>}
            {def.can_export && (
              <ExportButtons url={`/api/reports/${def.key}/export/?${new URLSearchParams(query).toString()}`} />
            )}
            {!def.can_export && def.key === "person-activity" && (
              <span className="hint">To print it, your administrator gives your role “Print their own activity”.</span>
            )}
          </>
        }
        filters={
          (def.has_dates || def.filters.length > 0) && (
            <>
              {def.has_dates && <DateRangeFilter range={range} />}
              {def.filters.length > 0 && (
                <div className="report-filters">
                  {def.filters.map((f) => {
                    const value = params.get(f.key) ?? "";
                    if (f.kind === "toggle") {
                      return (
                        <button
                          key={f.key}
                          type="button"
                          className={value ? "primary small" : "ghost small"}
                          aria-pressed={Boolean(value)}
                          onClick={() => setFilters({ [f.key]: value ? "" : "1" })}
                        >
                          {value ? "✓ " : ""}{f.label}
                        </button>
                      );
                    }
                    if (f.kind === "text") {
                      return (
                        <TextFilter key={f.key} label={f.label} value={value}
                          onChange={(v) => setFilters({ [f.key]: v })} />
                      );
                    }
                    return (
                      <label className="field" key={f.key}>
                        {f.label}
                        <select value={value} onChange={(e) => setFilters({ [f.key]: e.target.value })}>
                          <option value="">{f.blank || "All"}</option>
                          {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                      </label>
                    );
                  })}
                </div>
              )}
            </>
          )
        }
      >
        {(rows) => (
          <div className="table-wrap">
            <table className="grid report-grid">
              <thead>
                <tr>
                  {def.columns.map((c) => (
                    <SortHeader key={c.key} column={c} sort={sort} onSort={(next) => setFilters({ sort: next })} />
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i}>
                    {def.columns.map((c) => (
                      <td key={c.key} className={c.numeric ? "num right" : c.wrap ? "wrap" : ""}>
                        <ReportCell cell={row[c.key]} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ListCard>

      {extra && (
        <>
        {extra.partial && (
          <p className="report-stamp">Only the samples you can see are included, so this may not be the whole picture.</p>
        )}
        <p className="report-stamp">Generated {extra.generated_at} ({extra.timezone}) for {extra.generated_by}</p>
        </>
      )}
    </>
  );
}

export default function ReportPage() {
  const { reportKey = "" } = useParams();
  const [def, setDef] = useState<ReportDefinition | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setDef(null);
    setError("");
    apiGet<ReportDefinition>(`/api/reports/${reportKey}/definition/`)
      .then(setDef)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not open this report."));
  }, [reportKey]);

  if (error) {
    return (
      <>
        <div className="breadcrumb"><Link to="/reports">Reports</Link></div>
        <Message kind="error">{error}</Message>
      </>
    );
  }
  if (!def) return <div className="card"><div className="card-body flush"><TableSkeleton rows={6} /></div></div>;
  return <ReportBody key={def.key} def={def} />;
}
