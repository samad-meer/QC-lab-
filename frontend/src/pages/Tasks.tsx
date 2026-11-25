import { useCallback, useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { useAuth } from "../auth";
import CommentModal from "../components/CommentModal";
import DueChip from "../components/DueChip";
import StepBadge from "../components/execution/StepBadge";
import { EmptyState, Message, TableSkeleton } from "../components/Feedback";
import LineIcon from "../components/LineIcon";
import type { IconName } from "../components/LineIcon";
import Stamp from "../components/Stamp";
import { useToast } from "../components/Toast";
import type { BatchStageTask, StepStatus, TaskBucket, TaskRow, Tasks as TasksData } from "../types";
import { daysUntil } from "../util";

const STEP_LABELS: Record<StepStatus, string> = {
  NOT_STARTED: "Not started",
  WAITING: "Waiting for receipt checks",
  COMPLETED: "Completed",
  AWAITING_ACCEPTANCE: "Awaiting acceptance",
  DECLINED: "Declined — needs reassigning",
  IN_PROGRESS: "In progress",
  REOPENED: "Reopened",
  FAILED: "Failed — retest needed",
  ON_HOLD: "On hold",
  SUBMITTED: "Submitted",
  PASSED: "Passed",
  RETURNED: "Returned",
};

/** A kind of task: a bucket the server fills, or the batch-record stages assigned to you. */
type Group = TaskBucket | "batch_stages";

const SECTIONS: { key: Group; title: string; short: string; hint: string; tone: string; icon: IconName }[] = [
  { key: "batch_stages", title: "Batch records assigned to you", short: "Batch record", hint: "Stages you fill and sign first, named for you by the production supervisor", tone: "hot", icon: "record" },
  { key: "receipts", title: "Receipt checks to complete", short: "Receipt checks", hint: "Testing cannot start until these are done", tone: "hot", icon: "inbox" },
  { key: "to_accept", title: "Handed to you", short: "Handed to you", hint: "Accept to start work, or decline with a reason", tone: "hot", icon: "handoff" },
  { key: "returned", title: "Returned for correction", short: "Returned", hint: "Sent back by a reviewer — their reason is below", tone: "fail", icon: "back" },
  { key: "to_review", title: "Awaiting your review", short: "Review", hint: "Stages your role signs, not already signed by you", tone: "hot", icon: "sign" },
  { key: "my_testing", title: "Your testing", short: "Testing", hint: "Samples you hold, with what each still needs", tone: "info", icon: "flask" },
  { key: "retests_to_decide", title: "Retests to decide", short: "Retest to decide", hint: "Failed results whose analyst asks for a retest", tone: "hot", icon: "retest" },
  { key: "needs_reassigning", title: "Declined — needs reassigning", short: "Needs reassigning", hint: "Someone declined the work; nobody holds it now", tone: "fail", icon: "people" },
  { key: "upcoming", title: "Assigned to you, coming up", short: "Coming up", hint: "Work named for you that has not reached you yet", tone: "muted", icon: "clock" },
  { key: "sent", title: "Handovers you sent", short: "Handover sent", hint: "Waiting for the other person to accept", tone: "muted", icon: "send" },
  { key: "my_retests", title: "Your retest requests", short: "Your retest request", hint: "Waiting for a decision, or authorized and not yet entered", tone: "muted", icon: "retest" },
  { key: "on_hold", title: "On hold", short: "On hold", hint: "Nothing can be entered or signed until released", tone: "warn", icon: "pause" },
  { key: "overdue", title: "Overdue", short: "Overdue", hint: "Past the due date and not yet released", tone: "fail", icon: "alert" },
];
const SECTION = Object.fromEntries(SECTIONS.map((s) => [s.key, s])) as Record<Group, (typeof SECTIONS)[number]>;

const ACTIONABLE: TaskBucket[] = ["receipts", "to_accept", "returned", "to_review", "my_testing", "retests_to_decide", "needs_reassigning"];
const ALSO: TaskBucket[] = ["upcoming", "sent", "my_retests", "on_hold", "overdue"];

/** The board: tasks by what you have to do about them, left to right. */
type ColumnKey = "todo" | "doing" | "review" | "waiting" | "overdue";
const COLUMNS: { key: ColumnKey; title: string; hint: string }[] = [
  { key: "todo", title: "To do", hint: "Yours to start, accept or put right" },
  { key: "doing", title: "In progress", hint: "Work you hold now" },
  { key: "review", title: "To review and sign", hint: "Waiting for your signature" },
  { key: "waiting", title: "Waiting on others", hint: "Not yours to act on yet" },
  { key: "overdue", title: "Overdue", hint: "Past the due date, not yet released" },
];
const COLUMN_OF: Record<TaskBucket, ColumnKey> = {
  receipts: "todo", to_accept: "todo", returned: "todo", retests_to_decide: "todo", needs_reassigning: "todo",
  my_testing: "doing", to_review: "review",
  upcoming: "waiting", sent: "waiting", my_retests: "waiting", on_hold: "waiting",
  overdue: "overdue",
};

/** One task, drawn the same way in the list and on the board. */
interface Card {
  id: string;
  group: Group;
  column: ColumnKey;
  search: string;
  late: boolean;
  head: ReactNode;
  body: ReactNode;
  actions?: ReactNode;
}

type View = "list" | "board";
const VIEW_KEY = "qclab.tasks.view";

function savedView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === "board" ? "board" : "list";
  } catch {
    return "list";
  }
}

function SampleHead({ row, review }: { row: TaskRow; review?: boolean }) {
  const s = row.sample;
  return (
    <div className="tk-head">
      <Link to={review ? `/samples/${s.id}/review` : `/samples/${s.id}`} className="task-no">{s.sample_no}</Link>
      <div className="cell-sub">{s.product_name} · {s.batch_label}</div>
      <DueChip due={s.due_date} done={s.status === "APPROVED"} />
    </div>
  );
}

/**
 * Everything waiting on the signed-in person, worked out by the server
 * from the same rules it enforces — never from what a screen has loaded.
 * Shown as a list by kind of task, or as a board by what to do next; the
 * tiles, the search and Late only narrow both.
 */
export default function Tasks() {
  const toast = useToast();
  const { can } = useAuth();
  const location = useLocation();
  const [data, setData] = useState<TasksData | null>(null);
  const [error, setError] = useState("");
  const [decline, setDecline] = useState<{ kind: "handover" | "retest"; id: number; title: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<View>(savedView);
  const [focus, setFocus] = useState<Group | null>(null);
  const [search, setSearch] = useState("");
  const [lateOnly, setLateOnly] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await apiGet<TasksData>("/api/tasks/"));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your tasks.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // A link such as /tasks#receipts (from the dashboard) opens on that kind of task.
  useEffect(() => {
    const wanted = location.hash.slice(1);
    if (wanted && wanted in SECTION) setFocus(wanted as Group);
  }, [location.hash]);

  const choose = (next: View) => {
    setView(next);
    try {
      localStorage.setItem(VIEW_KEY, next);
    } catch {
      /* the choice just isn't remembered */
    }
  };

  const act = async (url: string, body: unknown, ok: string) => {
    setBusy(true);
    try {
      await apiPost(url, body);
      toast("ok", ok);
      await load();
    } catch (err) {
      toast("error", "Not done", err instanceof Error ? err.message : undefined);
    } finally {
      setBusy(false);
    }
  };

  if (error) return <Message kind="error">{error}</Message>;
  if (!data) return <div className="card"><div className="card-body flush"><TableSkeleton /></div></div>;

  const cardFor = (key: TaskBucket, row: TaskRow): Card => {
    const s = row.sample;
    let id = `${key}-${s.id}`;
    let body: ReactNode = null;
    let actions: ReactNode;
    switch (key) {
      case "receipts":
        actions = <Link to={`/samples/${s.id}`} className="btn-link">Do the checks →</Link>;
        body = <>
          {row.status && <StepBadge status={row.status} label={STEP_LABELS[row.status]} />}
          {row.blockers && row.blockers.length > 0
            ? <div className="cell-sub" style={{ marginTop: 6 }}>Still needed: {row.blockers.join(" · ")}</div>
            : <div className="cell-sub" style={{ marginTop: 6 }}>Every check is met — ready to complete.</div>}
        </>;
        break;
      case "to_accept": {
        const a = row.assignment!;
        id = `${key}-${a.id}`;
        actions = <>
          <button className="danger small" disabled={busy}
            onClick={() => setDecline({ kind: "handover", id: a.id, title: `${row.step_name} of ${s.sample_no}` })}>Decline…</button>
          <button className="primary small" disabled={busy}
            onClick={() => void act(`/api/assignments/${a.id}/respond/`, { action: "accept" }, `You accepted ${row.step_name} of ${s.sample_no}`)}>Accept</button>
        </>;
        body = <>
          <b>{row.step_name}</b> — {a.kind === "HANDOVER" ? "handed over" : "assigned"} to you
          <div className="cell-sub"><Stamp at={a.created_at} by={a.created_by} verb="by" />{a.from_user && <> · from {a.from_user.name}</>}</div>
          {a.note && <div className="task-quote">“{a.note}”</div>}
        </>;
        break;
      }
      case "returned":
        actions = <Link to={`/samples/${s.id}`} className="btn-link">Correct it →</Link>;
        body = <>
          <b>Returned from {row.returned?.from_step}</b> <span className="tag soft">attempt {row.attempt}</span>
          <div className="cell-sub"><Stamp at={row.returned?.at} by={row.returned?.by} verb="by" /></div>
          {row.returned?.reason && <div className="task-quote">“{row.returned.reason}”</div>}
          {row.blockers && row.blockers.length > 0 && <div className="cell-sub">Still needed: {row.blockers.join(" · ")}</div>}
        </>;
        break;
      case "my_testing":
        actions = <Link to={`/samples/${s.id}`} className="btn-link">Open →</Link>;
        body = <>
          {row.status && <StepBadge status={row.status} label={STEP_LABELS[row.status]} />}
          {row.blockers && row.blockers.length > 0
            ? <div className="cell-sub" style={{ marginTop: 6 }}>Still needed: {row.blockers.join(" · ")}</div>
            : <div className="cell-sub" style={{ marginTop: 6 }}>Ready to sign as “Analysed by”.</div>}
        </>;
        break;
      case "to_review":
        actions = <Link to={`/samples/${s.id}/review`} className="btn-link">Review →</Link>;
        body = <>
          <b>{row.step_name}</b>
          {row.needs_taking && <span className="badge hot" style={{ marginLeft: 8 }}>Take it first</span>}
          {row.blockers && row.blockers.length > 0 && <div className="cell-sub">Still needed: {row.blockers.join(" · ")}</div>}
        </>;
        break;
      case "retests_to_decide":
      case "my_retests": {
        const r = row.retest!;
        id = `${key}-${r.id}`;
        actions = key === "retests_to_decide" ? <>
          <button className="danger small" disabled={busy}
            onClick={() => setDecline({ kind: "retest", id: r.id, title: `the retest of ${r.test_name}` })}>Decline…</button>
          <button className="primary small" disabled={busy}
            onClick={() => window.confirm(`Authorize a retest of ${r.test_name}? The failure stays on record.`) && void act(`/api/retests/${r.id}/decide/`, { action: "authorize" }, `Retest of ${r.test_name} authorized`)}>Authorize</button>
        </> : undefined;
        body = <>
          <b>{r.test_name}</b> failed at <span className="num">{r.failed_value}</span>{" "}
          <span className="tag soft">{r.status_label}</span>
          <div className="cell-sub"><Stamp at={r.requested_at} by={r.requested_by} verb="asked by" /></div>
          <div className="task-quote">“{r.reason}”</div>
        </>;
        break;
      }
      case "needs_reassigning": {
        const a = row.assignment!;
        id = `${key}-${a.id}`;
        actions = <Link to={`/samples/${s.id}`} className="btn-link">Reassign →</Link>;
        body = <>
          <b>{row.step_name}</b> declined by {a.to_user.name}
          <div className="cell-sub"><Stamp at={a.responded_at} /></div>
          {a.response_reason && <div className="task-quote">“{a.response_reason}”</div>}
        </>;
        break;
      }
      case "sent": {
        const a = row.assignment!;
        id = `${key}-${a.id}`;
        body = <>
          <b>{row.step_name}</b> → {a.to_user.name} <span className="tag soft">{a.status_label}</span>
          <div className="cell-sub"><Stamp at={a.created_at} verb="sent" /></div>
        </>;
        break;
      }
      case "upcoming":
        id = `${key}-${s.id}-${row.step}`;
        body = row.status === "WAITING"
          ? <><b>Testing</b> — assigned to you; it opens when the front desk completes the receipt checks</>
          : <><b>{row.step_name}</b> — named for you; it reaches you after the earlier steps</>;
        break;
      case "on_hold":
        body = <>
          “{row.hold?.reason}”
          <div className="cell-sub"><Stamp at={row.hold?.placed_at} by={row.hold?.placed_by} verb="placed by" /></div>
        </>;
        break;
      default:
        actions = <Link to={`/samples/${s.id}`} className="btn-link">Open →</Link>;
        body = <span className="badge fail">{s.status_label}</span>;
    }
    return {
      id, group: key, column: COLUMN_OF[key], body, actions,
      search: [s.sample_no, s.product_name, s.batch_label, row.step_name].join(" ").toLowerCase(),
      late: daysUntil(s.due_date) < 0 && s.status !== "APPROVED",
      head: <SampleHead row={row} review={key === "to_review"} />,
    };
  };

  const stageCard = (w: BatchStageTask): Card => {
    const to = `/batches/${w.batch.id}#stage-${w.stage.id}`;
    const need = w.state === "fill"
      ? { tone: "hot", text: `${w.missing} value${w.missing === 1 ? "" : "s"} to write` }
      : w.state === "sign" ? { tone: "info", text: `Sign “${w.column}”` }
      : { tone: "muted", text: "Waiting for earlier stages" };
    return {
      id: `stage-${w.batch.id}-${w.stage.id}`,
      group: "batch_stages",
      column: w.state === "fill" ? "todo" : w.state === "sign" ? "review" : "waiting",
      search: [w.batch.official_batch_no, w.batch.internal_id, w.batch.product, w.stage.name].join(" ").toLowerCase(),
      late: false,
      head: (
        <div className="tk-head">
          <Link to={to} className="task-no">{w.batch.official_batch_no}</Link>
          <div className="cell-sub">{w.batch.product}</div>
          <div className="cell-sub mono">{w.batch.internal_id}</div>
        </div>
      ),
      body: <>
        <b>{w.stage.order}. {w.stage.name}</b> <span className={`badge ${need.tone}`}>{need.text}</span>
        {w.state === "waiting" && <div className="cell-sub">Waits for {w.waiting_for.join(", ")} to pass first.</div>}
        {w.state === "sign" && <div className="cell-sub">Every value is written: sign “{w.column}” with your password.</div>}
        <div className="cell-sub">
          Assigned by {w.assigned_by?.name ?? "—"}, <Stamp at={w.assigned_at} />{w.note && <> — “{w.note}”</>}
        </div>
      </>,
      actions: <Link className="btn-link" to={to}>Open the stage →</Link>,
    };
  };

  const batchWork = data.batch_stages ?? [];
  const fills = can("batch.record.fill");
  // Production fills batch records and never works on samples: their tiles would all read 0.
  const sampleWork = !fills || can("result.enter") || can("sample.register") || can("sample.view.all");
  const batchToDo = batchWork.filter((w) => w.state !== "waiting").length;

  const all: Card[] = [
    ...batchWork.map(stageCard),
    ...SECTIONS.filter((s) => s.key !== "batch_stages")
      .flatMap((s) => data[s.key as TaskBucket].map((row) => cardFor(s.key as TaskBucket, row))),
  ];
  const q = search.trim().toLowerCase();
  const shown = all.filter((c) => (!focus || c.group === focus) && (!lateOnly || c.late) && (!q || c.search.includes(q)));
  const narrowed = Boolean(focus || lateOnly || q);
  const pick = (g: Group) => setFocus((now) => (now === g ? null : g));
  const clear = () => {
    setFocus(null);
    setLateOnly(false);
    setSearch("");
  };
  const columns = COLUMNS.filter((c) => sampleWork || (c.key !== "doing" && c.key !== "overdue"));
  const also = sampleWork ? ALSO.filter((k) => data.counts[k] > 0) : [];

  return (
    <>
      <div className="page-head page-head-split">
        <div>
          <h1>My tasks</h1>
          <p className="sub">Everything waiting on you, worked out by the server from the same rules it enforces.</p>
        </div>
        <div className="page-head-aside">
          {can("report.view") && (
            <p className="task-reports">
              {can("report.open.person-activity") && <Link to="/reports/person-activity" className="btn-link">My weekly or monthly report →</Link>}
              {can("report.open.tasks-by-person") && <Link to="/reports/tasks-by-person" className="btn-link">Everyone's tasks →</Link>}
            </p>
          )}
          <Stamp at={data.generated_at} verb="Updated" />
        </div>
      </div>

      <div className="task-tiles tk-tiles" role="group" aria-label="Show one kind of task">
        {fills && (
          <button type="button" aria-pressed={focus === "batch_stages"} onClick={() => pick("batch_stages")}
            className={`task-tile ${batchToDo > 0 ? "hot" : "zero"}${focus === "batch_stages" ? " picked" : ""}`}>
            <b>{batchToDo}</b>
            <span>Batch records assigned to you</span>
          </button>
        )}
        {sampleWork && ACTIONABLE.map((k) => {
          const s = SECTION[k];
          const n = data.counts[k];
          return (
            <button key={k} type="button" aria-pressed={focus === k} onClick={() => pick(k)}
              className={`task-tile ${n > 0 ? s.tone : "zero"}${focus === k ? " picked" : ""}`}>
              <b>{n}</b>
              <span>{s.title}</span>
            </button>
          );
        })}
      </div>

      {also.length > 0 && (
        <div className="tk-also" role="group" aria-label="Show other tasks">
          <span>Also:</span>
          {also.map((k) => (
            <button key={k} type="button" className={`chip-toggle${k === "overdue" ? " tk-late-chip" : ""}`}
              aria-pressed={focus === k} onClick={() => pick(k)}>
              {data.counts[k]} {SECTION[k].short.toLowerCase()}
            </button>
          ))}
        </div>
      )}

      <div className="tk-toolbar">
        <label className="tk-search">
          <LineIcon name="search" size={16} />
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sample, product or batch" aria-label="Search tasks" />
        </label>
        <button type="button" className="chip-toggle" aria-pressed={lateOnly} onClick={() => setLateOnly((v) => !v)}>
          Late only
        </button>
        {focus && (
          <button type="button" className="chip-toggle tk-focus" aria-pressed onClick={() => setFocus(null)}
            title="Show every kind of task again">
            {SECTION[focus].short} <LineIcon name="close" size={12} />
          </button>
        )}
        {narrowed && <button type="button" className="link-btn" onClick={clear}>Clear</button>}
        <span className="grow" />
        <span className="tk-count">{narrowed ? `${shown.length} of ${all.length}` : `${all.length}`} task{all.length === 1 ? "" : "s"}</span>
        <div className="seg" role="group" aria-label="View">
          <button type="button" className={view === "list" ? "on" : ""} aria-pressed={view === "list"} onClick={() => choose("list")}>
            <LineIcon name="list" size={15} /> List
          </button>
          <button type="button" className={view === "board" ? "on" : ""} aria-pressed={view === "board"} onClick={() => choose("board")}>
            <LineIcon name="board" size={15} /> Board
          </button>
        </div>
      </div>

      {all.length === 0 ? (
        <div className="card">
          <EmptyState icon="✓" title="Nothing is waiting on you"
            sub={fills ? "Batch-record stages assigned to you will appear here." : "New work, handovers and returned samples will appear here."} />
        </div>
      ) : shown.length === 0 ? (
        <div className="card">
          <EmptyState icon="⌕" title="No task matches" sub="Nothing here fits the filters you have chosen." />
          <div style={{ textAlign: "center", paddingBottom: 20 }}>
            <button type="button" className="ghost small" onClick={clear}>Clear the filters</button>
          </div>
        </div>
      ) : view === "list" ? (
        SECTIONS.filter((s) => shown.some((c) => c.group === s.key)).map((s) => {
          const cards = shown.filter((c) => c.group === s.key);
          return (
            <section key={s.key} id={s.key} className="card tk-section">
              <div className="card-head">
                <span className={`tk-ico ${s.tone}`}><LineIcon name={s.icon} size={16} /></span>
                <h2>{s.title}</h2>
                <span className={`badge ${s.tone}`}>{cards.length}</span>
                <span className="hint">{s.hint}</span>
              </div>
              <ul className="tk-list">
                {cards.map((c) => (
                  <li key={c.id} className={`tk-row${c.late ? " late" : ""}`}>
                    {c.head}
                    <div className="tk-row-body">{c.body}</div>
                    <div className="tk-row-actions">{c.actions}</div>
                  </li>
                ))}
              </ul>
            </section>
          );
        })
      ) : (
        <div className="tk-board" style={{ "--tk-cols": columns.length } as CSSProperties}>
          {columns.map((col) => {
            const cards = shown.filter((c) => c.column === col.key);
            return (
              <section key={col.key} className={`tk-col ${col.key}`} aria-label={col.title}>
                <div className="tk-col-head">
                  <b>{col.title}</b>
                  <span className="tk-col-count">{cards.length}</span>
                  <small>{col.hint}</small>
                </div>
                {cards.length === 0 ? (
                  <p className="tk-col-empty">Nothing here</p>
                ) : cards.map((c) => {
                  const s = SECTION[c.group];
                  return (
                    <article key={c.id} className={`tk-card ${s.tone}${c.late ? " late" : ""}`}>
                      <span className={`tk-chip ${s.tone}`}><LineIcon name={s.icon} size={12} />{s.short}</span>
                      {c.head}
                      <div className="tk-card-body">{c.body}</div>
                      {c.actions && <div className="tk-card-actions">{c.actions}</div>}
                    </article>
                  );
                })}
              </section>
            );
          })}
        </div>
      )}

      {decline && (
        <CommentModal
          title={`Decline ${decline.title}`}
          label="Why?"
          confirmText="Decline"
          hint={decline.kind === "handover" ? "The sender will see your reason. The work stays where it was." : "The failed result stands. The analyst will see your reason."}
          onConfirm={async (reason) => {
            if (decline.kind === "handover") {
              await apiPost(`/api/assignments/${decline.id}/respond/`, { action: "reject", reason });
            } else {
              await apiPost(`/api/retests/${decline.id}/decide/`, { action: "decline", comment: reason });
            }
            setDecline(null);
            toast("info", "Declined");
            await load();
          }}
          onClose={() => setDecline(null)}
        />
      )}
    </>
  );
}
