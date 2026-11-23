import { useState } from "react";
import { apiPost } from "../../api";
import { useAuth } from "../../auth";
import type { Blocker, Execution, StepView } from "../../types";
import CommentModal from "../CommentModal";
import { Message } from "../Feedback";
import Stamp from "../Stamp";
import { useToast } from "../Toast";
import AssignModal from "./AssignModal";
import ChecklistRowView from "./ChecklistRowView";
import Documents from "./Documents";
import StepBadge from "./StepBadge";
import Threads from "./Threads";

const OUTCOME: Record<string, [string, string]> = {
  SUBMITTED: ["Submitted", "pass"],
  PASSED: ["Passed", "pass"],
  COMPLETED: ["Completed", "pass"],
  RETURNED: ["Returned", "fail"],
};

/** What still stands between this step and its signature. */
export function BlockerList({
  blockers,
  canWaive,
  onWaive,
}: {
  blockers: Blocker[];
  canWaive?: boolean;
  onWaive?: (b: Blocker) => void;
}) {
  return (
    <ul className="blockers">
      {blockers.map((b, i) => (
        <li key={`${b.code}-${b.item_id ?? i}`}>
          <span className="blocker-icon" aria-hidden="true">!</span>
          <span style={{ flex: 1 }}>{b.message}</span>
          {canWaive && b.waivable && onWaive && (
            <button type="button" className="ghost small" onClick={() => onWaive(b)}>Waive…</button>
          )}
        </li>
      ))}
    </ul>
  );
}

/**
 * Everything inside one step of a sample's journey: who holds it, what it
 * still needs, its checklist and documents, its notes, and its history —
 * every entry with the person and the exact time.
 */
export default function StepPanel({
  sampleId,
  exec,
  step,
  onChange,
}: {
  sampleId: number;
  exec: Execution;
  step: StepView;
  onChange: (e: Execution) => void;
}) {
  const { user } = useAuth();
  const toast = useToast();
  const [modal, setModal] = useState<"assign" | "handover" | "decline" | "cancel" | null>(null);
  const [waiving, setWaiving] = useState<Blocker | null>(null);
  const [busy, setBusy] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const userId = user?.id ?? 0;

  const run = async (url: string, body: unknown, ok: string) => {
    setBusy(true);
    try {
      onChange(await apiPost<Execution>(url, body));
      toast("ok", ok);
    } catch (err) {
      toast("error", "Not done", err instanceof Error ? err.message : undefined);
    } finally {
      setBusy(false);
    }
  };

  const pending = step.pending;
  const required = step.checklist.filter((r) => r.item.required).length;
  const met = step.checklist.filter((r) => r.waiver || (r.response && r.response.conforms)).length;
  const actionable = step.is_current && step.status !== "ON_HOLD";
  const receipt = step.kind === "receipt";
  const completed = receipt ? step.decisions[0] : undefined;
  const historyCount = step.decisions.length + step.assignments.length;

  return (
    <div className="exec-step">
      <div className="exec-head">
        <StepBadge status={step.status} label={step.status_label} />
        <div className="exec-who">
          {receipt ? (
            completed ? (
              <>Completed — <Stamp at={completed.at} by={completed.by} /></>
            ) : (
              <>Made by the <b>front desk</b> when the sample arrives — testing waits for them</>
            )
          ) : step.holder ? (
            <>Held by <b>{step.holder.name}</b></>
          ) : step.kind === "review" ? (
            <>Open to anyone in the <b>{step.role_name}</b> role{step.requires_acceptance ? " — must be taken first" : ""}</>
          ) : (
            <>Nobody holds the testing</>
          )}
          {exec.attempt > 1 && step.is_current && <span className="tag soft">attempt {exec.attempt}</span>}
        </div>
        <div className="spacer" />
        <div className="actions-bar">
          {step.can.complete && (
            <button className="primary small" disabled={busy}
              onClick={() => void run(`/api/samples/${sampleId}/receipt/complete/`, {}, "Receipt checks completed — the analyst has been told")}>
              Complete receipt checks
            </button>
          )}
          {step.can.take && (
            <button className="primary small" disabled={busy}
              onClick={() => void run(`/api/samples/${sampleId}/assignments/`, { mode: "take", step: step.key }, `You now hold “${step.name}”`)}>
              Take this stage
            </button>
          )}
          {step.can.hand_over && <button className="ghost small" onClick={() => setModal("handover")}>Hand over…</button>}
          {step.can.assign && (
            <button className="ghost small" onClick={() => setModal("assign")}>{step.holder ? "Reassign…" : "Assign…"}</button>
          )}
        </div>
      </div>

      {pending && (
        <div className={`handover-card ${step.can.accept ? "mine" : ""}`}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <b>
              {pending.kind === "HANDOVER" ? "Handover" : "Assignment"} to {pending.to_user.name} — awaiting acceptance
            </b>
            <div className="cell-sub">
              <Stamp at={pending.created_at} by={pending.created_by} verb="sent by" />
              {pending.from_user && <> · from {pending.from_user.name}</>}
            </div>
            {pending.note && <div className="handover-note">“{pending.note}”</div>}
          </div>
          <div className="actions-bar">
            {step.can.accept && (
              <>
                <button className="danger small" disabled={busy} onClick={() => setModal("decline")}>Decline…</button>
                <button className="primary small" disabled={busy}
                  onClick={() => void run(`/api/assignments/${pending.id}/respond/`, { action: "accept" }, `You accepted “${step.name}”`)}>
                  Accept
                </button>
              </>
            )}
            {step.can.cancel && !step.can.accept && (
              <button className="ghost small" disabled={busy} onClick={() => setModal("cancel")}>Cancel handover</button>
            )}
          </div>
        </div>
      )}

      {step.status === "WAITING" && (
        <div className="exec-note">Testing opens as soon as the front desk completes the receipt checks.</div>
      )}

      {actionable && step.work_blockers.length > 0 && !step.can.accept && (
        <div className="exec-note">You can't work on this step: {step.work_blockers[0].message}</div>
      )}

      {actionable && (step.blockers.length > 0 ? (
        <div className="exec-section">
          <h4>{receipt ? "Still needed before testing can start" : "Still needed before it can be signed"}</h4>
          <BlockerList blockers={step.blockers} canWaive={step.can.waive} onWaive={setWaiving} />
        </div>
      ) : (
        <Message kind="ok">Every requirement of this step is met.</Message>
      ))}

      <div className="exec-section">
        <h4>
          Checklist and required documents
          {step.checklist.length > 0 && <span className="hint">{met} of {step.checklist.length} met · {required} required</span>}
        </h4>
        {step.checklist.length === 0 ? (
          <div className="cell-sub">No checks are configured for this step. An administrator adds them on the Workflows screen.</div>
        ) : (
          <div className="check-list">
            {step.checklist.map((row) => (
              <ChecklistRowView key={row.item.id} sampleId={sampleId} step={step} row={row}
                attachments={step.attachments} onChange={onChange} />
            ))}
          </div>
        )}
      </div>

      <div className="exec-section">
        <h4>Files <span className="hint">{step.attachments.filter((a) => a.is_current).length} current</span></h4>
        <Documents sampleId={sampleId} step={step} userId={userId} maxMb={exec.max_upload_mb} onChange={onChange} />
      </div>

      <div className="exec-section">
        <h4>Notes and feedback <span className="hint">Kept forever — amendments keep the original</span></h4>
        <Threads sampleId={sampleId} stepKey={step.key} comments={step.comments} userId={userId}
          canComment={exec.can_comment} onChange={onChange} />
      </div>

      <div className="exec-section">
        <button type="button" className="link-btn" onClick={() => setShowHistory((v) => !v)} aria-expanded={showHistory}>
          {showHistory ? "Hide" : "Show"} this step's history ({historyCount} {historyCount === 1 ? "entry" : "entries"})
        </button>
        {showHistory && (
          <ul className="timeline" style={{ marginTop: 10 }}>
            {step.decisions.map((d, i) => (
              <li key={`d${i}`}>
                <span className="when">{d.at && <Stamp at={d.at} />}</span>
                <span>
                  <span className={`badge ${OUTCOME[d.outcome][1]}`}>{OUTCOME[d.outcome][0]}</span>{" "}
                  attempt {d.attempt}{d.by && <> · <b>{d.by.name}</b></>}
                  {d.reason && <span className="comment">“{d.reason}”</span>}
                </span>
              </li>
            ))}
            {step.assignments.map((a) => (
              <li key={`a${a.id}`}>
                <span className="when"><Stamp at={a.created_at} /></span>
                <span>
                  <b>{a.created_by.name}</b> — {a.kind_label.toLowerCase()} to <b>{a.to_user.name}</b>{" "}
                  <span className="tag soft">{a.status_label}</span>
                  {a.responded_at && a.status !== "PENDING" && (
                    <> · <Stamp at={a.responded_at} by={a.responded_by} verb={a.status === "ACCEPTED" ? "accepted" : a.status.toLowerCase()} /></>
                  )}
                  {a.note && <span className="comment">“{a.note}”</span>}
                  {a.response_reason && a.status !== "ACCEPTED" && <span className="comment">“{a.response_reason}”</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {(modal === "assign" || modal === "handover") && (
        <AssignModal sampleId={sampleId} step={step} mode={modal} onDone={(e) => { onChange(e); toast("ok", modal === "handover" ? "Handover sent" : "Assignment saved"); }}
          onClose={() => setModal(null)} />
      )}
      {modal === "decline" && pending && (
        <CommentModal
          title={`Decline “${step.name}”`}
          hint={`${pending.created_by.name} will see your reason. The work stays where it was.`}
          label="Why are you declining?"
          confirmText="Decline"
          placeholder="e.g. Container seal broken on arrival — cannot accept this sample."
          onConfirm={async (reason) => {
            onChange(await apiPost<Execution>(`/api/assignments/${pending.id}/respond/`, { action: "reject", reason }));
            setModal(null);
          }}
          onClose={() => setModal(null)}
        />
      )}
      {modal === "cancel" && pending && (
        <CommentModal
          title="Cancel the handover"
          label="Reason (optional)"
          confirmText="Cancel handover"
          optional
          onConfirm={async (reason) => {
            onChange(await apiPost<Execution>(`/api/assignments/${pending.id}/respond/`, { action: "cancel", reason }));
            setModal(null);
          }}
          onClose={() => setModal(null)}
        />
      )}
      {waiving && (
        <CommentModal
          title="Waive a requirement"
          hint={`${waiving.message} Waiving is recorded with your name, and you will not be able to ${receipt ? "complete" : "sign"} this step yourself.`}
          label="Why can it be set aside?"
          confirmText="Waive it"
          tone="primary"
          onConfirm={async (reason) => {
            onChange(await apiPost<Execution>(`/api/samples/${sampleId}/waivers/`, { item_id: waiving.item_id, reason }));
            setWaiving(null);
            toast("ok", "Requirement waived");
          }}
          onClose={() => setWaiving(null)}
        />
      )}
    </div>
  );
}
