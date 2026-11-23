import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { useAuth } from "../auth";
import CommentModal from "../components/CommentModal";
import StepBadge from "../components/execution/StepBadge";
import { EmptyState, Message, TableSkeleton } from "../components/Feedback";
import Stamp from "../components/Stamp";
import { useToast } from "../components/Toast";
import type { BatchStageTask, StepStatus, TaskBucket, TaskRow, Tasks as TasksData } from "../types";
import { daysUntil, fmtDate } from "../util";

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

const SECTIONS: { key: TaskBucket; title: string; hint: string; tone: string }[] = [
  { key: "receipts", title: "Receipt checks to complete", hint: "Testing cannot start until these are done", tone: "hot" },
  { key: "to_accept", title: "Handed to you", hint: "Accept to start work, or decline with a reason", tone: "hot" },
  { key: "returned", title: "Returned for correction", hint: "Sent back by a reviewer — their reason is below", tone: "fail" },
  { key: "to_review", title: "Awaiting your review", hint: "Stages your role signs, not already signed by you", tone: "hot" },
  { key: "my_testing", title: "Your testing", hint: "Samples you hold, with what each still needs", tone: "info" },
  { key: "retests_to_decide", title: "Retests to decide", hint: "Failed results whose analyst asks for a retest", tone: "hot" },
  { key: "needs_reassigning", title: "Declined — needs reassigning", hint: "Someone declined the work; nobody holds it now", tone: "fail" },
  { key: "upcoming", title: "Assigned to you, coming up", hint: "Work named for you that has not reached you yet", tone: "muted" },
  { key: "sent", title: "Handovers you sent", hint: "Waiting for the other person to accept", tone: "muted" },
  { key: "my_retests", title: "Your retest requests", hint: "Waiting for a decision, or authorized and not yet entered", tone: "muted" },
  { key: "on_hold", title: "On hold", hint: "Nothing can be entered or signed until released", tone: "warn" },
  { key: "overdue", title: "Overdue", hint: "Past the due date and not yet released", tone: "fail" },
];

const ACTIONABLE: TaskBucket[] = ["receipts", "to_accept", "returned", "to_review", "my_testing", "retests_to_decide", "needs_reassigning"];

/** A batch-record stage assigned to you: what it needs now. */
function StageWork({ w }: { w: BatchStageTask }) {
  const to = `/batches/${w.batch.id}#stage-${w.stage.id}`;
  const need = w.state === "fill"
    ? { tone: "hot", text: `${w.missing} value${w.missing === 1 ? "" : "s"} to write` }
    : w.state === "sign" ? { tone: "info", text: `Sign “${w.column}”` }
    : { tone: "muted", text: "Waiting for earlier stages" };
  return (
    <li className="task-item">
      <div className="task-sample">
        <Link to={to} className="task-no">{w.batch.official_batch_no}</Link>
        <div className="cell-sub">{w.batch.product}</div>
        <div className="cell-sub mono">{w.batch.internal_id}</div>
      </div>
      <div className="task-body">
        <b>{w.stage.order}. {w.stage.name}</b> <span className={`badge ${need.tone}`}>{need.text}</span>
        {w.state === "waiting" && <div className="cell-sub">Waits for {w.waiting_for.join(", ")} to pass first.</div>}
        {w.state === "sign" && <div className="cell-sub">Every value is written: sign “{w.column}” with your password.</div>}
        <div className="cell-sub">
          Assigned by {w.assigned_by?.name ?? "—"}, <Stamp at={w.assigned_at} />{w.note && <> — “{w.note}”</>}
        </div>
      </div>
      <div className="actions-bar task-actions">
        <Link className="link-button" to={to}>Open the stage →</Link>
      </div>
    </li>
  );
}

function SampleCell({ row, review }: { row: TaskRow; review?: boolean }) {
  const s = row.sample;
  const days = daysUntil(s.due_date);
  return (
    <div className="task-sample">
      <Link to={review ? `/samples/${s.id}/review` : `/samples/${s.id}`} className="task-no">{s.sample_no}</Link>
      <div className="cell-sub">{s.product_name} · {s.batch_label}</div>
      <div className={`cell-sub ${days < 0 && s.status !== "APPROVED" ? "due-late" : ""}`}>
        Due {fmtDate(s.due_date)}{days < 0 && s.status !== "APPROVED" ? ` · ${-days} day${days === -1 ? "" : "s"} late` : ""}
      </div>
    </div>
  );
}

function Item({ row, review, children, actions }: { row: TaskRow; review?: boolean; children: ReactNode; actions?: ReactNode }) {
  return (
    <li className="task-item">
      <SampleCell row={row} review={review} />
      <div className="task-body">{children}</div>
      {actions && <div className="actions-bar task-actions">{actions}</div>}
    </li>
  );
}

/**
 * Everything waiting on the signed-in person, worked out by the server
 * from the same rules it enforces — never from what a screen has loaded.
 */
export default function Tasks() {
  const toast = useToast();
  const { can } = useAuth();
  const [data, setData] = useState<TasksData | null>(null);
  const [error, setError] = useState("");
  const [decline, setDecline] = useState<{ kind: "handover" | "retest"; id: number; title: string } | null>(null);
  const [busy, setBusy] = useState(false);

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

  const render = (key: TaskBucket, row: TaskRow) => {
    switch (key) {
      case "receipts":
        return (
          <Item key={`${key}${row.sample.id}`} row={row} actions={<Link to={`/samples/${row.sample.id}`} className="btn-link">Do the checks →</Link>}>
            {row.status && <StepBadge status={row.status} label={STEP_LABELS[row.status]} />}
            {row.blockers && row.blockers.length > 0
              ? <div className="cell-sub" style={{ marginTop: 6 }}>Still needed: {row.blockers.join(" · ")}</div>
              : <div className="cell-sub" style={{ marginTop: 6 }}>Every check is met — ready to complete.</div>}
          </Item>
        );
      case "to_accept": {
        const a = row.assignment!;
        return (
          <Item key={`${key}${a.id}`} row={row} actions={<>
            <button className="danger small" disabled={busy}
              onClick={() => setDecline({ kind: "handover", id: a.id, title: `${row.step_name} of ${row.sample.sample_no}` })}>Decline…</button>
            <button className="primary small" disabled={busy}
              onClick={() => void act(`/api/assignments/${a.id}/respond/`, { action: "accept" }, `You accepted ${row.step_name} of ${row.sample.sample_no}`)}>Accept</button>
          </>}>
            <b>{row.step_name}</b> — {a.kind === "HANDOVER" ? "handed over" : "assigned"} to you
            <div className="cell-sub"><Stamp at={a.created_at} by={a.created_by} verb="by" />{a.from_user && <> · from {a.from_user.name}</>}</div>
            {a.note && <div className="task-quote">“{a.note}”</div>}
          </Item>
        );
      }
      case "returned":
        return (
          <Item key={`${key}${row.sample.id}`} row={row} actions={<Link to={`/samples/${row.sample.id}`} className="btn-link">Correct it →</Link>}>
            <b>Returned from {row.returned?.from_step}</b> <span className="tag soft">attempt {row.attempt}</span>
            <div className="cell-sub"><Stamp at={row.returned?.at} by={row.returned?.by} verb="by" /></div>
            {row.returned?.reason && <div className="task-quote">“{row.returned.reason}”</div>}
            {row.blockers && row.blockers.length > 0 && <div className="cell-sub">Still needed: {row.blockers.join(" · ")}</div>}
          </Item>
        );
      case "my_testing":
        return (
          <Item key={`${key}${row.sample.id}`} row={row} actions={<Link to={`/samples/${row.sample.id}`} className="btn-link">Open →</Link>}>
            {row.status && <StepBadge status={row.status} label={STEP_LABELS[row.status]} />}
            {row.blockers && row.blockers.length > 0
              ? <div className="cell-sub" style={{ marginTop: 6 }}>Still needed: {row.blockers.join(" · ")}</div>
              : <div className="cell-sub" style={{ marginTop: 6 }}>Ready to sign as “Analysed by”.</div>}
          </Item>
        );
      case "to_review":
        return (
          <Item key={`${key}${row.sample.id}`} row={row} review actions={<Link to={`/samples/${row.sample.id}/review`} className="btn-link">Review →</Link>}>
            <b>{row.step_name}</b>
            {row.needs_taking && <span className="badge hot" style={{ marginLeft: 8 }}>Take it first</span>}
            {row.blockers && row.blockers.length > 0 && <div className="cell-sub">Still needed: {row.blockers.join(" · ")}</div>}
          </Item>
        );
      case "retests_to_decide":
      case "my_retests": {
        const r = row.retest!;
        return (
          <Item key={`${key}${r.id}`} row={row} actions={key === "retests_to_decide" ? <>
            <button className="danger small" disabled={busy}
              onClick={() => setDecline({ kind: "retest", id: r.id, title: `the retest of ${r.test_name}` })}>Decline…</button>
            <button className="primary small" disabled={busy}
              onClick={() => window.confirm(`Authorize a retest of ${r.test_name}? The failure stays on record.`) && void act(`/api/retests/${r.id}/decide/`, { action: "authorize" }, `Retest of ${r.test_name} authorized`)}>Authorize</button>
          </> : undefined}>
            <b>{r.test_name}</b> failed at <span className="num">{r.failed_value}</span>{" "}
            <span className="tag soft">{r.status_label}</span>
            <div className="cell-sub"><Stamp at={r.requested_at} by={r.requested_by} verb="asked by" /></div>
            <div className="task-quote">“{r.reason}”</div>
          </Item>
        );
      }
      case "needs_reassigning": {
        const a = row.assignment!;
        return (
          <Item key={`${key}${a.id}`} row={row} actions={<Link to={`/samples/${row.sample.id}`} className="btn-link">Reassign →</Link>}>
            <b>{row.step_name}</b> declined by {a.to_user.name}
            <div className="cell-sub"><Stamp at={a.responded_at} /></div>
            {a.response_reason && <div className="task-quote">“{a.response_reason}”</div>}
          </Item>
        );
      }
      case "sent": {
        const a = row.assignment!;
        return (
          <Item key={`${key}${a.id}`} row={row}>
            <b>{row.step_name}</b> → {a.to_user.name} <span className="tag soft">{a.status_label}</span>
            <div className="cell-sub"><Stamp at={a.created_at} verb="sent" /></div>
          </Item>
        );
      }
      case "upcoming":
        return (
          <Item key={`${key}${row.sample.id}${row.step}`} row={row}>
            {row.status === "WAITING"
              ? <><b>Testing</b> — assigned to you; it opens when the front desk completes the receipt checks</>
              : <><b>{row.step_name}</b> — named for you; it reaches you after the earlier steps</>}
          </Item>
        );
      case "on_hold":
        return (
          <Item key={`${key}${row.sample.id}`} row={row}>
            “{row.hold?.reason}”
            <div className="cell-sub"><Stamp at={row.hold?.placed_at} by={row.hold?.placed_by} verb="placed by" /></div>
          </Item>
        );
      default:
        return (
          <Item key={`${key}${row.sample.id}`} row={row}>
            <span className="badge fail">{row.sample.status_label}</span>
          </Item>
        );
    }
  };

  const nonEmpty = SECTIONS.filter((s) => data[s.key].length > 0);
  const batchWork = data.batch_stages ?? [];
  const fills = can("batch.record.fill");
  // Production fills batch records and never works on samples: their tiles would all read 0.
  const sampleWork = !fills || can("result.enter") || can("sample.register") || can("sample.view.all");
  const batchToDo = batchWork.filter((w) => w.state !== "waiting").length;

  return (
    <>
      <div className="page-head page-head-split">
        <div>
          <h1>My tasks</h1>
          <p className="sub">Everything waiting on you, worked out by the server from the same rules it enforces.</p>
        </div>
        <div className="page-head-aside"><Stamp at={data.generated_at} verb="Updated" /></div>
      </div>

      <div className="task-tiles">
        {fills && (
          <a href="#batch_stages" className={`task-tile ${batchToDo > 0 ? "hot" : "zero"}`}>
            <b>{batchToDo}</b>
            <span>Batch records assigned to you</span>
          </a>
        )}
        {sampleWork && ACTIONABLE.map((k) => {
          const s = SECTIONS.find((x) => x.key === k)!;
          const n = data.counts[k];
          return (
            <a key={k} href={`#${k}`} className={`task-tile ${n > 0 ? s.tone : "zero"}`}>
              <b>{n}</b>
              <span>{s.title}</span>
            </a>
          );
        })}
      </div>

      {batchWork.length > 0 && (
        <section id="batch_stages" className="card">
          <div className="card-head">
            <h2>Batch records assigned to you</h2>
            <span className={`badge ${batchToDo > 0 ? "hot" : "muted"}`}>{batchWork.length}</span>
            <span className="hint">Stages you fill and sign first, named for you by the production supervisor</span>
          </div>
          <ul className="task-list">
            {batchWork.map((w) => <StageWork key={`${w.batch.id}-${w.stage.id}`} w={w} />)}
          </ul>
        </section>
      )}

      {nonEmpty.length === 0 ? (
        batchWork.length > 0 ? null : (
          <div className="card">
            <EmptyState icon="✓" title="Nothing is waiting on you"
              sub={fills ? "Batch-record stages assigned to you will appear here." : "New work, handovers and returned samples will appear here."} />
          </div>
        )
      ) : (
        nonEmpty.map((s) => (
          <section key={s.key} id={s.key} className="card">
            <div className="card-head">
              <h2>{s.title}</h2>
              <span className={`badge ${s.tone}`}>{data[s.key].length}</span>
              <span className="hint">{s.hint}</span>
            </div>
            <ul className="task-list">{data[s.key].map((row) => render(s.key, row))}</ul>
          </section>
        ))
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
