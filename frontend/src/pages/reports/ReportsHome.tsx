import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../../api";
import { useAuth } from "../../auth";
import { BarList } from "../../components/Charts";
import { Message, TableSkeleton } from "../../components/Feedback";
import LabGlance from "../../components/LabGlance";
import DateRangeFilter from "../../components/list/DateRangeFilter";
import { TimelineChart } from "../../components/reports/LineCharts";
import type { ReportCatalogue, ReportDashboard, ReportTile } from "../../types";
import { useDateRange } from "../../useList";

function Tile({ tile }: { tile: ReportTile }) {
  const empty = tile.value === 0 || tile.value === "—";
  const tone = empty ? "zero" : tile.alert ? "fail" : "info";
  const inside = (
    <>
      <b>{tile.value}</b>
      <span>{tile.label}</span>
      {tile.sub && <small>{tile.sub}</small>}
    </>
  );
  // No link when the records behind it are in a report this role does not open.
  if (!tile.to) return <div className={`task-tile ${tone} still`}>{inside}</div>;
  return (
    <Link to={tile.to} className={`task-tile ${tone}`} title="Open the records behind this number">
      {inside}
    </Link>
  );
}

/** The main reporting screen: the lab now, the period, and the way into every report. */
export default function ReportsHome() {
  const { can } = useAuth();
  // The overview's figures are the Sample Register's, and open it.
  const overview = can("report.open.sample-register");
  const range = useDateRange({ defaultPeriod: "month" });
  const [data, setData] = useState<ReportDashboard | null>(null);
  const [catalogue, setCatalogue] = useState<ReportCatalogue | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!overview) return;
    try {
      setData(await apiGet<ReportDashboard>(`/api/reports/dashboard/?${range.search}`));
      setError("");
    } catch (err) {
      setData(null);
      setError(err instanceof Error ? err.message : "Could not load the dashboard.");
    }
  }, [range.search, overview]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    apiGet<ReportCatalogue>("/api/reports/").then(setCatalogue).catch(() => setCatalogue(null));
  }, []);

  return (
    <>
      <div className="page-head">
        <h1>Reports</h1>
        <p className="sub">
          {overview
            ? "What is happening in the laboratory, worked out from the records themselves. Every number opens the "
              + "records behind it."
            : "The reports open to your role, worked out from the records themselves."}
        </p>
      </div>

      {error && <div style={{ marginBottom: 16 }}><Message kind="error">{error}</Message></div>}

      {!overview ? null : !data && !error ? (
        <div className="card"><div className="card-body flush"><TableSkeleton rows={5} /></div></div>
      ) : data ? (
        <>
          <section className="card" aria-label="Right now">
            <div className="card-head">
              <h2>Right now</h2>
              <span className="hint">{data.scope}. Not affected by the dates below.</span>
            </div>
            <div className="card-body">
              <div className="task-tiles" style={{ marginBottom: 0 }}>
                {data.now.map((t) => <Tile key={t.key} tile={t} />)}
              </div>
            </div>
          </section>

          <div className="actions-bar" style={{ marginBottom: 14 }}>
            <DateRangeFilter range={range} />
          </div>

          <LabGlance data={data} />

          <section className="card" aria-label="In this period">
            <div className="card-head">
              <h2>In this period</h2>
              <span className="hint">{data.label}</span>
            </div>
            <div className="card-body">
              <div className="task-tiles" style={{ marginBottom: 0 }}>
                {data.period.map((t) => <Tile key={t.key} tile={t} />)}
              </div>
            </div>
          </section>

          <section className="card" aria-label="Failures">
            <div className="card-head">
              <h2>Failures in this period</h2>
              <span className="hint">Three different things, counted apart</span>
              <div className="spacer" />
              {data.failures.to && <Link to={data.failures.to} className="btn-link">OOS report →</Link>}
            </div>
            <div className="card-body">
              <div className="kv report-failures">
                <div>
                  <div className="k">Failed test results</div>
                  <div className="v">{data.failures.tests}</div>
                  <div className="cell-sub">One result outside its specification</div>
                </div>
                <div>
                  <div className="k">Samples with a failed test</div>
                  <div className="v">{data.failures.samples}</div>
                  <div className="cell-sub">At least one of its results failed</div>
                </div>
                <div>
                  <div className="k">Batches with a failed test</div>
                  <div className="v">{data.failures.batches}</div>
                  <div className="cell-sub">A failed test does not decide a batch</div>
                </div>
                <div>
                  <div className="k">Batches rejected</div>
                  <div className="v">{data.failures.rejected_batches}</div>
                  <div className="cell-sub">A disposition decided by the quality unit</div>
                </div>
              </div>
            </div>
          </section>

          <div className="report-charts wide">
            <section className="card" aria-label="Samples received and completed">
              <div className="card-head"><h2>Samples received and completed</h2><span className="hint">{data.label}</span></div>
              <div className="card-body">
                <TimelineChart data={data.charts.flow} emptyText="Nothing was received or completed in this period." />
              </div>
            </section>
            <section className="card" aria-label="Pass and fail trend">
              <div className="card-head"><h2>Pass and fail trend</h2><span className="hint">Test results, retests included</span></div>
              <div className="card-body">
                <TimelineChart data={data.charts.outcomes} emptyText="No results were entered in this period." />
              </div>
            </section>
          </div>
          <div className="report-charts">
            <section className="card" aria-label="Samples by workflow status">
              <div className="card-head"><h2>Samples by workflow status</h2><span className="hint">Right now</span></div>
              <div className="card-body"><BarList data={data.charts.status} /></div>
            </section>
            <section className="card" aria-label="Samples by laboratory section">
              <div className="card-head"><h2>Samples by laboratory section</h2><span className="hint">{data.label}</span></div>
              <div className="card-body">
                <BarList data={data.charts.sections} emptyText="No samples were received in this period." />
              </div>
            </section>
            {data.charts.analysts && (
              <section className="card" aria-label="Pending and overdue work by analyst">
                <div className="card-head"><h2>Pending and overdue work by analyst</h2><span className="hint">Right now</span></div>
                <div className="card-body">
                  <BarList
                    data={data.charts.analysts.map((a) => ({
                      label: a.label, value: a.pending, to: a.to,
                      sub: a.overdue > 0 ? `${a.overdue} overdue` : "None overdue",
                    }))}
                    emptyText="Nothing is waiting on an analyst."
                  />
                </div>
              </section>
            )}
          </div>

          <p className="report-stamp">Generated {data.generated_at} ({data.timezone}) for {data.generated_by}</p>
        </>
      ) : null}

      {catalogue && catalogue.categories.length === 0 && (
        <Message kind="info">
          No report is open to your role yet. An administrator chooses which reports each role opens, on the Roles
          screen.
        </Message>
      )}

      {catalogue && catalogue.categories.length > 0 && (
        <section aria-label="All reports">
          <h2 className="report-group-title">All reports</h2>
          <div className="report-directory">
            {catalogue.categories.map((category) => (
              <div className="card" key={category.key}>
                <div className="card-head">
                  <div>
                    <h2>{category.title}</h2>
                    <span className="hint">{category.question}</span>
                  </div>
                </div>
                <div className="report-links">
                  {category.reports.map((r) => (
                    <Link key={r.key} to={r.to}>
                      <b>{r.title}</b>
                      <small>{r.description}</small>
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
