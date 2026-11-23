import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../../api";
import { BarList, ColumnChart, Meter, Stat } from "../../components/Charts";
import { Message, TableSkeleton } from "../../components/Feedback";
import DateRangeFilter from "../../components/list/DateRangeFilter";
import type { AnalyticsData } from "../../types";
import { useDateRange } from "../../useList";
import { fmtDateTime } from "../../util";

const STATUS_LABEL: Record<string, string> = {
  RECEIVED: "Received",
  IN_TESTING: "In testing",
  IN_REVIEW: "In review",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  CANCELLED: "Cancelled",
};

const SEVERITY_ICON: Record<string, string> = {
  signature: "✓",
  refused: "!",
  attention: "↩",
  admin: "⚙",
  normal: "•",
  quiet: "·",
};

export default function Analytics() {
  const range = useDateRange({ defaultPeriod: "week" });
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await apiGet<AnalyticsData>(`/api/auth/analytics/?${range.search}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load analytics.");
    } finally {
      setLoading(false);
    }
  }, [range.search]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <div className="page-head">
        <h1>Lab analytics</h1>
        <p className="sub">
          Everything here is worked out from the records themselves — no figure is stored, so
          nothing can drift out of step with what actually happened.
        </p>
      </div>

      <div className="actions-bar" style={{ marginBottom: 18 }}>
        <DateRangeFilter range={range} />
        <div className="spacer" />
        {data && (
          <span style={{ fontSize: 12.5, color: "var(--ink-3)" }}>
            {data.label}
            {data.period === "custom" ? "" : data.from ? ` · from ${fmtDateTime(data.from)}` : " · everything on record"}
          </span>
        )}
      </div>

      {error && <Message kind="error">{error}</Message>}

      {loading && !data ? (
        <div className="card">
          <div className="card-body flush">
            <TableSkeleton rows={5} />
          </div>
        </div>
      ) : data ? (
        <>
          {/* Headline numbers: a KPI row, not a chart of six bars. */}
          <div className="stat-row">
            <Stat
              label="Samples received"
              value={data.throughput.received}
              sub={data.label.toLowerCase()}
            />
            <Stat
              label="Certificates released"
              value={data.throughput.released}
              sub={`${data.throughput.prints} copies printed`}
            />
            <Stat
              label="Median turnaround"
              value={data.turnaround.median_days === null ? "—" : `${data.turnaround.median_days}d`}
              sub={
                data.turnaround.samples > 0
                  ? `${data.turnaround.samples} finished · slowest ${data.turnaround.slowest_days}d`
                  : "nothing finished yet"
              }
            />
            <Stat
              label="Past due"
              value={data.pipeline.overdue}
              sub={`${data.pipeline.live} still in the lab`}
              alert={data.pipeline.overdue > 0}
            />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16, marginBottom: 18 }}>
            <div className="card" style={{ margin: 0 }}>
              <div className="card-head">
                <h2>Where samples are now</h2>
                <span className="hint">Live pipeline, not the period</span>
              </div>
              <div className="card-body">
                <BarList
                  data={Object.entries(data.pipeline.by_status).map(([key, value]) => ({
                    label: STATUS_LABEL[key] ?? key,
                    value,
                  }))}
                />
              </div>
            </div>

            <div className="card" style={{ margin: 0 }}>
              <div className="card-head">
                <h2>Result quality</h2>
                <span className="hint">{data.label}</span>
              </div>
              <div className="card-body" style={{ display: "grid", gap: 18 }}>
                <div>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
                    <span style={{ fontSize: 27, fontWeight: 700 }}>{data.quality.oos_rate}%</span>
                    <span style={{ fontSize: 13, color: "var(--ink-3)" }}>
                      out of specification
                    </span>
                  </div>
                  <Meter
                    value={data.quality.oos_rate}
                    max={Math.max(10, data.quality.oos_rate)}
                    tone={data.quality.oos_rate > 0 ? "fail" : "brand"}
                    caption={`${data.quality.failures} failing of ${data.quality.graded_results} graded results`}
                  />
                </div>
                <div className="kv" style={{ gridTemplateColumns: "1fr 1fr" }}>
                  <div>
                    <div className="k">Results corrected</div>
                    <div className="v">{data.quality.corrections}</div>
                  </div>
                  <div>
                    <div className="k">Sent back / rejected</div>
                    <div className="v">{data.quality.sent_back}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h2>Activity per day</h2>
              <span className="hint">
                {data.activity.events} recorded actions · {data.activity.signatures} signatures ·{" "}
                {data.activity.refusals} refused
              </span>
            </div>
            <div className="card-body">
              <ColumnChart data={data.activity.daily} />
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16, marginBottom: 18 }}>
            <div className="card" style={{ margin: 0 }}>
              <div className="card-head">
                <h2>Workload by analyst</h2>
                <span className="hint">{data.label}</span>
              </div>
              <div className="card-body">
                <BarList
                  data={data.workload.map((w) => ({
                    label: w.analyst,
                    value: w.total,
                    sub: `${w.done} completed`,
                  }))}
                  emptyText="No samples were assigned in this period."
                />
              </div>
            </div>

            <div className="card" style={{ margin: 0 }}>
              <div className="card-head">
                <h2>Samples by section</h2>
                <span className="hint">{data.label}</span>
              </div>
              <div className="card-body">
                <BarList
                  data={data.by_section.map((s) => ({ label: s.name, value: s.count }))}
                  emptyText="No samples were received in this period."
                />
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h2>Needs attention</h2>
              <span className="hint">Refusals, corrections and returned work</span>
              <div className="spacer" />
              <Link to="/admin/audit" className="btn-link">Full audit trail →</Link>
            </div>
            <div className="card-body">
              {data.attention.length === 0 ? (
                <div style={{ color: "var(--ink-3)", fontSize: 13.5 }}>
                  Nothing was refused, corrected or sent back in this period.
                </div>
              ) : (
                <div className="feed">
                  {data.attention.map((e) => (
                    <div className="feed-item" key={e.id}>
                      <div className={`feed-dot ${e.severity}`} aria-hidden="true">
                        {SEVERITY_ICON[e.severity] ?? "•"}
                      </div>
                      <div className="feed-text">
                        <b>{e.actor_name}</b> {e.sentence}
                      </div>
                      <div className="feed-meta">{fmtDateTime(e.at)}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}
