import { useEffect, useState } from "react";
import { apiGet } from "../api";
import ListCard from "../components/list/ListCard";
import SampleFilters, { useSampleFilters } from "../components/SampleFilters";
import SampleTable from "../components/SampleTable";
import type { SampleListItem, SampleStatus, Summary } from "../types";
import { useList, useUrlFilters } from "../useList";

const FILTERS: { key: SampleStatus | "ALL"; label: string }[] = [
  { key: "ALL", label: "All" },
  { key: "RECEIVED", label: "Received" },
  { key: "IN_TESTING", label: "In testing" },
  { key: "IN_REVIEW", label: "In review" },
  { key: "APPROVED", label: "Approved" },
];

export default function Samples() {
  // The dashboard links straight to one status: /samples?status=IN_REVIEW
  const { params, setFilters } = useUrlFilters();
  const status = FILTERS.find((f) => f.key === params.get("status"))?.key ?? "ALL";
  const filters = useSampleFilters();
  const { range } = filters;
  const list = useList<SampleListItem>("/api/samples/", { query: { ...filters.query, status } });
  const [summary, setSummary] = useState<Summary | null>(null);

  useEffect(() => {
    apiGet<Summary>(`/api/summary/?${range.search}`).then(setSummary).catch(() => undefined);
  }, [range.search, list.data]);

  return (
    <>
      <div className="page-head">
        <h1>All samples</h1>
        <p className="sub">The whole pipeline, newest first. Select a sample to open it.</p>
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

      <ListCard
        title="Samples"
        exportable
        list={list}
        failure="Could not load samples"
        emptyTitle="No samples match these filters"
        emptySub="Try a different status or a wider date range."
        actions={
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
        }
        filters={<SampleFilters filters={filters} />}
      >
        {(rows) => <SampleTable samples={rows} />}
      </ListCard>
    </>
  );
}
