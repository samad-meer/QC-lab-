import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPoll } from "../api";
import { LAB_REGISTER_VIEWS, useAuth } from "../auth";
import { Message } from "../components/Feedback";
import { NotificationList, useNotifications } from "../components/Notifications";
import { TimelineChart } from "../components/reports/LineCharts";
import Stamp from "../components/Stamp";
import type { BatchRow, BatchStageTask, Page, ReportDashboard, Summary, TaskBucket, Tasks } from "../types";
import { fmtNow } from "../util";

/** Line icons on a 24 grid, drawn like the rest of the app's. */
const ICONS = {
  inbox: "M22 12h-6l-2 3h-4l-2-3H2M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z",
  handoff: "M5 12h14M13 6l6 6-6 6",
  back: "M9 14 4 9l5-5M4 9h11a5 5 0 0 1 0 10h-1",
  sign: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
  flask: "M9 3h6M10 3v6l-5.5 9.5A1.5 1.5 0 0 0 5.8 21h12.4a1.5 1.5 0 0 0 1.3-2.5L14 9V3",
  retest: "M21 4v6h-6M3 20v-6h6M5.5 9a8 8 0 0 1 13.2-3L21 10M3 14l2.3 4A8 8 0 0 0 18.5 15",
  people: "M16 19c0-2.8-1.8-5-4-5s-4 2.2-4 5M12 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6M20 18c0-2-1-3.6-2.5-4.4M17 5.2a3 3 0 0 1 0 5.6",
  record: "M9 4h6a1 1 0 0 1 1 1v1H8V5a1 1 0 0 1 1-1M8 6H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-2M9 13h6M9 17h4",
  list: "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01",
  box: "M21 8l-9-5-9 5 9 5 9-5M3 8v8l9 5 9-5V8M12 13v8",
  book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  flow: "M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6M18 9a9 9 0 0 1-9 9",
  door: "M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3",
  check: "M20 6 9 17l-5-5",
  alert: "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0",
  bell: "M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0",
};
type IconName = keyof typeof ICONS;

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name]} />
    </svg>
  );
}

/** What can be waiting on someone, worded as the Tasks page words it. */
const WAITING: { key: TaskBucket; title: string; hint: string; tone: "hot" | "fail" | "info"; icon: IconName }[] = [
  { key: "receipts", title: "Receipt checks to complete", hint: "Testing cannot start until these are done", tone: "hot", icon: "inbox" },
  { key: "to_accept", title: "Handed to you", hint: "Accept to start work, or decline with a reason", tone: "hot", icon: "handoff" },
  { key: "returned", title: "Returned for correction", hint: "Sent back by a reviewer, with their reason", tone: "fail", icon: "back" },
  { key: "to_review", title: "Awaiting your review", hint: "Stages your role signs", tone: "hot", icon: "sign" },
  { key: "my_testing", title: "Your testing", hint: "Samples you hold, with what each still needs", tone: "info", icon: "flask" },
  { key: "retests_to_decide", title: "Retests to decide", hint: "An analyst asks for a retest", tone: "hot", icon: "retest" },
  { key: "needs_reassigning", title: "Declined, needs reassigning", hint: "Nobody holds this work now", tone: "fail", icon: "people" },
];
/** Not yours to act on yet, but worth knowing. */
const LATER: { key: TaskBucket; label: string }[] = [
  { key: "upcoming", label: "coming up" },
  { key: "sent", label: "handovers waiting" },
  { key: "my_retests", label: "retest requests" },
  { key: "on_hold", label: "on hold" },
  { key: "overdue", label: "overdue" },
];
/** Where unfinished samples are. Approved ones are counted apart: they are done. */
const STAGES: { key: "RECEIVED" | "IN_TESTING" | "IN_REVIEW"; label: string; color: string }[] = [
  { key: "RECEIVED", label: "Received", color: "var(--warn)" },
  { key: "IN_TESTING", label: "In testing", color: "var(--chart-1)" },
  { key: "IN_REVIEW", label: "In review", color: "var(--chart-2)" },
];
const REFRESH_MS = 60_000;

function greeting(now: Date) {
  const h = fmtNow(now).hour;
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

/** "Dr. Nadia Hussain" → "Dr. Nadia"; "Ahmed Raza" → "Ahmed". */
function firstName(name: string) {
  const words = name.trim().split(/\s+/);
  return words[0]?.endsWith(".") && words[1] ? `${words[0]} ${words[1]}` : words[0] || name;
}

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

function stageWork(w: BatchStageTask): string {
  if (w.state === "fill") return `${plural(w.missing, "value")} to fill`;
  if (w.state === "sign") return `Sign “${w.column}”`;
  return `Waits for ${w.waiting_for.join(", ")}`;
}

/**
 * The start page: what is waiting on you today, how the lab is doing this
 * month, where unfinished samples and recent batches stand, and your latest
 * notifications. Each part shows only to someone who can act on it or open it.
 */
export default function Dashboard() {
  const { user, can, titles } = useAuth();
  const { data: notes, markAll } = useNotifications();
  const [tasks, setTasks] = useState<Tasks | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [month, setMonth] = useState<ReportDashboard | null>(null);
  const [batches, setBatches] = useState<BatchRow[] | null>(null);
  const [error, setError] = useState("");
  const [now, setNow] = useState(() => new Date());

  const fills = can("batch.record.fill");
  // Production fills batch records and never works on samples: sample counts would all read 0.
  const sampleWork = !fills || can("result.enter") || can("sample.register") || can("sample.view.all");
  const overview = can("report.view") && can("report.open.sample-register");
  const seesBatches = can("batch.view.all") || can("sample.view.all");

  const load = useCallback(async (quietly = false) => {
    const get = quietly ? apiPoll : apiGet;
    try {
      const [t, s] = await Promise.all([get<Tasks>("/api/tasks/"), get<Summary>("/api/summary/")]);
      setTasks(t);
      setSummary(s);
      setError("");
    } catch (err) {
      if (!quietly) setError(err instanceof Error ? err.message : "Could not load the dashboard.");
    }
    // The extras never block the page: each shows when it arrives, or not at all.
    if (overview) get<ReportDashboard>("/api/reports/dashboard/?period=month").then(setMonth).catch(() => undefined);
    if (seesBatches) {
      get<Page<BatchRow>>("/api/batches/?page_size=5").then((p) => setBatches(p.results)).catch(() => undefined);
    }
  }, [overview, seesBatches]);

  useEffect(() => {
    void load();
    const refresh = window.setInterval(() => void load(true), REFRESH_MS);
    const tick = window.setInterval(() => setNow(new Date()), 1000);
    return () => {
      window.clearInterval(refresh);
      window.clearInterval(tick);
    };
  }, [load]);

  if (!user) return null;
  const first = firstName(user.name);
  const unread = notes?.unread ?? 0;
  const batchWork = tasks?.batch_stages ?? [];
  const batchToDo = batchWork.filter((w) => w.state !== "waiting");
  const later = sampleWork ? LATER.filter((l) => (tasks?.counts[l.key] ?? 0) > 0) : [];
  const waitingTotal = tasks ? tasks.actionable : null;
  const overdue = summary?.overdue ?? 0;

  const shortcuts = [
    can("sample.register") && { to: "/frontdesk", label: "Receive a sample", icon: "inbox" as IconName },
    can("result.enter") && { to: "/worklist", label: "My worklist", icon: "flask" as IconName },
    user.is_reviewer && { to: "/queue", label: "Awaiting my signature", icon: "sign" as IconName },
    can("sample.view.all") && { to: "/samples", label: "All samples", icon: "list" as IconName },
    seesBatches && { to: "/batches", label: "Batches", icon: "box" as IconName },
    LAB_REGISTER_VIEWS.some(can) && { to: "/lab", label: "Lab records", icon: "book" as IconName },
    can("report.view") && { to: "/reports", label: "Reports", icon: "chart" as IconName },
    can("workflow.manage") && { to: "/admin/workflows", label: "Workflows", icon: "flow" as IconName },
    can("user.manage") && { to: "/admin/sign-in", label: "Who is signed in", icon: "door" as IconName },
  ].filter((x): x is { to: string; label: string; icon: IconName } => Boolean(x));

  const inProgress = summary ? STAGES.reduce((sum, st) => sum + (summary.by_status[st.key] ?? 0), 0) : 0;

  return (
    <>
      <section className="dash-hero">
        <div>
          <div className="dash-kicker">{titles.lab_name}</div>
          <h1>{greeting(now)}, {first}</h1>
          <p>{user.designation || user.role?.name || ""}</p>
          <div className="dash2-today" aria-label="Today">
            <Link to="/tasks" className={`dash2-pill ${waitingTotal ? "hot" : ""}`}>
              <Icon name="check" size={14} />
              {waitingTotal === null ? "…" : waitingTotal ? `${plural(waitingTotal, "item")} waiting on you` : "Nothing waiting on you"}
            </Link>
            {sampleWork && overdue > 0 && (
              <Link to="/tasks#overdue" className="dash2-pill fail">
                <Icon name="alert" size={14} />{plural(overdue, "sample")} overdue
              </Link>
            )}
            {unread > 0 && (
              <a href="#dash-notifications" className="dash2-pill">
                <Icon name="bell" size={14} />{unread} unread
              </a>
            )}
          </div>
        </div>
        <div className="dash-clock" aria-label="Current date and time">
          {/* The lab's time and clock, as everything else shows it, wherever the browser is. */}
          <b>{fmtNow(now).time}</b>
          <span>{fmtNow(now).date}</span>
        </div>
      </section>

      {error && <div style={{ marginBottom: 16 }}><Message kind="error">{error}</Message></div>}

      <section className="card" aria-label="Waiting on you">
        <div className="card-head">
          <h2>Waiting on you</h2>
          {tasks && <span className="hint">Updated <Stamp at={tasks.generated_at} /></span>}
          <div className="spacer" />
          <Link to="/tasks" className="btn-link">All my tasks →</Link>
        </div>
        <div className="card-body">
          {tasks && tasks.actionable === 0 && (
            <div className="dash2-caught">
              <Icon name="check" size={16} />
              <span><b>You're all caught up.</b> New work shows here, and in My tasks, as soon as it reaches you.</span>
            </div>
          )}
          <div className="dash2-tiles">
            {fills && (
              <Link to="/tasks#batch_stages" className={`dash2-tile ${tasks && batchToDo.length > 0 ? "hot" : "zero"}`}
                title="Stages assigned to you that still need values or your signature">
                <span className="dash2-ico"><Icon name="record" /></span>
                <b>{tasks ? batchToDo.length : "–"}</b>
                <span>Batch records assigned to you</span>
              </Link>
            )}
            {sampleWork && WAITING.map((w) => {
              const n = tasks?.counts[w.key] ?? 0;
              return (
                <Link key={w.key} to={`/tasks#${w.key}`} title={w.hint}
                  className={`dash2-tile ${tasks && n > 0 ? w.tone : "zero"}`}>
                  <span className="dash2-ico"><Icon name={w.icon} /></span>
                  <b>{tasks ? n : "–"}</b>
                  <span>{w.title}</span>
                </Link>
              );
            })}
          </div>
          {later.length > 0 && (
            <div className="dash2-later">
              <span>Also:</span>
              {later.map((l) => (
                <Link key={l.key} to={`/tasks#${l.key}`} className={l.key === "overdue" ? "late" : undefined}>
                  {tasks?.counts[l.key]} {l.label}
                </Link>
              ))}
            </div>
          )}
        </div>
      </section>

      <div className="dash2-grid">
        <div className="dash2-col">
          {fills && batchWork.length > 0 && (
            <section className="card" aria-label="Your batch records">
              <div className="card-head">
                <h2>Your batch records</h2>
                <span className="hint">Stages assigned to you</span>
              </div>
              <div className="card-body flush">
                <ul className="dash2-rows">
                  {batchWork.slice(0, 6).map((w) => (
                    <li key={`${w.batch.id}-${w.stage.id}`}>
                      <Link to={`/batches/${w.batch.id}`}>
                        <span>
                          <b>{w.batch.official_batch_no}</b> · {w.stage.order}. {w.stage.name}
                          <small>{w.batch.product}</small>
                        </span>
                        <span className={`badge ${w.state === "fill" ? "hot" : w.state === "sign" ? "info" : "muted"}`}>
                          {stageWork(w)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}

          {overview && month && (
            <section className="card" aria-label="This month">
              <div className="card-head">
                <h2>This month in the lab</h2>
                <span className="hint">{month.label} · {month.scope}</span>
                <div className="spacer" />
                <Link to="/reports" className="btn-link">Reports →</Link>
              </div>
              <div className="card-body">
                <div className="dash2-kpis">
                  {month.period.map((t) => {
                    const inner = (
                      <>
                        <b>{t.value}</b>
                        <span>{t.label}</span>
                        {t.sub && <small>{t.sub}</small>}
                      </>
                    );
                    return t.to
                      ? <Link key={t.key} to={t.to} className="dash2-kpi">{inner}</Link>
                      : <div key={t.key} className="dash2-kpi">{inner}</div>;
                  })}
                  {(() => {
                    const inner = (
                      <>
                        <b className={month.failures.tests ? "late" : undefined}>{month.failures.tests}</b>
                        <span>Failed test results</span>
                        <small>{plural(month.failures.samples, "sample")}, {plural(month.failures.batches, "batch", "batches")}</small>
                      </>
                    );
                    return month.failures.to
                      ? <Link to={month.failures.to} className="dash2-kpi">{inner}</Link>
                      : <div className="dash2-kpi">{inner}</div>;
                  })()}
                </div>
                <div className="dash2-chart">
                  <div className="dash2-chart-title">Samples received and completed</div>
                  <TimelineChart data={month.charts.flow} emptyText="Nothing was received or completed this month." />
                </div>
              </div>
            </section>
          )}

          {seesBatches && batches && (
            <section className="card" aria-label="Recent batches">
              <div className="card-head">
                <h2>Recent batches</h2>
                <span className="hint">QC stages passed of those required for release</span>
                <div className="spacer" />
                <Link to="/batches" className="btn-link">All batches →</Link>
              </div>
              <div className="card-body flush">
                {batches.length === 0 ? (
                  <p className="cell-sub" style={{ padding: "16px 20px", margin: 0 }}>No batches yet.</p>
                ) : (
                  <ul className="dash2-rows">
                    {batches.map((b) => {
                      const p = b.qc_progress;
                      const share = p && p.required ? p.passed / p.required : 0;
                      return (
                        <li key={b.id}>
                          <Link to={`/batches/${b.id}`}>
                            <span>
                              <b>{b.official_batch_no}</b>
                              <small>{b.product.name} · {plural(b.sample_count ?? 0, "sample")}</small>
                            </span>
                            {p ? (
                              <span className="dash2-progress" title={`${p.passed} of ${p.required} required stages passed`}>
                                <span className="dash2-bar">
                                  <i style={{ width: `${Math.round(share * 100)}%` }}
                                    className={p.failed ? "failed" : share === 1 ? "done" : undefined} />
                                </span>
                                <small>{p.failed ? "A stage failed" : `${p.passed} of ${p.required} passed`}</small>
                              </span>
                            ) : (
                              <small className="cell-sub">No QC stages</small>
                            )}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </section>
          )}
        </div>

        <div className="dash2-col">
          {sampleWork && (
            <section className="card" aria-label="Samples in progress">
              <div className="card-head">
                <h2>Samples in progress</h2>
                <span className="hint">{can("sample.view.all") ? "Across the lab" : "The ones you work on"}</span>
              </div>
              <div className="card-body">
                {!summary ? (
                  <div className="dash2-pipe sk" />
                ) : (
                  <>
                    <div className="dash2-pipe" role="img"
                      aria-label={STAGES.map((st) => `${summary.by_status[st.key] ?? 0} ${st.label.toLowerCase()}`).join(", ")}>
                      {inProgress === 0 ? <span className="dash2-pipe-empty" /> : STAGES.map((st) => {
                        const n = summary.by_status[st.key] ?? 0;
                        return n > 0 && (
                          <span key={st.key} style={{ flexGrow: n, background: st.color }} title={`${st.label}: ${n}`} />
                        );
                      })}
                    </div>
                    <div className="dash2-stats">
                      {STAGES.map((st) => (
                        <Link key={st.key} to={can("sample.view.all") ? `/samples?status=${st.key}` : "/tasks"} className="dash-stat">
                          <b>{summary.by_status[st.key] ?? 0}</b>
                          <span><i style={{ background: st.color }} />{st.label}</span>
                        </Link>
                      ))}
                      <Link to={can("sample.view.all") ? "/samples?status=APPROVED" : "/tasks"} className="dash-stat">
                        <b>{summary.by_status.APPROVED ?? 0}</b>
                        <span><i style={{ background: "var(--pass)" }} />Approved</span>
                      </Link>
                      <Link to="/tasks#overdue" className={`dash-stat ${overdue > 0 ? "late" : ""}`}>
                        <b>{overdue}</b>
                        <span><i style={{ background: "var(--fail)" }} />Overdue</span>
                      </Link>
                    </div>
                  </>
                )}
              </div>
            </section>
          )}

          <section className="card" id="dash-notifications" aria-label="Notifications">
            <div className="card-head">
              <h2>Notifications</h2>
              {unread > 0 && <span className="badge hot">{unread} unread</span>}
              <div className="spacer" />
              {unread > 0 && <button type="button" className="link-btn" onClick={() => void markAll()}>Mark all read</button>}
            </div>
            <div className="card-body flush">
              <NotificationList items={notes?.items ?? []} limit={6} />
            </div>
          </section>

          {shortcuts.length > 0 && (
            <section className="card" aria-label="Go to">
              <div className="card-head"><h2>Go to</h2></div>
              <div className="card-body">
                <div className="dash2-quick">
                  {shortcuts.map((s) => (
                    <Link key={s.to} to={s.to}>
                      <span className="dash2-ico"><Icon name={s.icon} /></span>
                      {s.label}
                    </Link>
                  ))}
                </div>
              </div>
            </section>
          )}
        </div>
      </div>
    </>
  );
}
