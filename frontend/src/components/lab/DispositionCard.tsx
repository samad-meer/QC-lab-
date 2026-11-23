import { useState } from "react";
import { apiPost } from "../../api";
import type { BatchDetail } from "../../types";
import CommentModal from "../CommentModal";
import { Message } from "../Feedback";
import Stamp from "../Stamp";
import { useToast } from "../Toast";

const TONES: Record<string, string> = { RELEASED: "pass", REJECTED: "fail", QUARANTINED: "warn" };

/** The quality unit's decision about a batch. The latest one is the batch's status. */
export default function DispositionCard({ batch, onChange }: {
  batch: BatchDetail;
  onChange: (next: BatchDetail) => void;
}) {
  const toast = useToast();
  const { disposition } = batch;
  const [deciding, setDeciding] = useState(false);
  const [decision, setDecision] = useState("");
  const [password, setPassword] = useState("");
  const close = () => {
    setDeciding(false);
    setDecision("");
    setPassword("");
  };
  const blocked = disposition.release_problems.length > 0;

  return (
    <section className="card" aria-label="Disposition">
      <div className="card-head">
        <h2>Disposition</h2>
        <span className={`badge ${TONES[disposition.decision] ?? "muted"}`}>{disposition.label}</span>
        <span className="hint">A certificate of analysis is not this decision</span>
        <div className="spacer" />
        {disposition.can_decide && <button className="primary small" onClick={() => setDeciding(true)}>Decide…</button>}
      </div>
      <div className="card-body doc-parts">
        {disposition.tested_it && (
          <Message kind="info">You tested a sample of this batch, so someone else must decide it.</Message>
        )}
        {disposition.can_decide && blocked && (
          <Message kind="warn">
            <b>It cannot be released yet.</b>
            {disposition.release_problems.map((p) => <div key={p}>{p}</div>)}
          </Message>
        )}
        {disposition.history.length === 0 ? (
          <p className="hint" style={{ margin: 0 }}>No decision has been made about this batch.</p>
        ) : (
          <ul className="timeline">
            {disposition.history.map((d) => (
              <li key={d.id}>
                <span className="when"><Stamp at={d.decided_at} /></span>
                <span>
                  <b>{d.decided_by.name}</b> <span className={`badge ${TONES[d.decision] ?? "muted"}`}>{d.label}</span>
                  <span className="comment">“{d.reason}”</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {deciding && (
        <CommentModal
          title={`Decide batch ${batch.official_batch_no}`}
          hint="This is the decision about the batch, signed with your password. It stays on record, and a later decision is added beside it."
          label="Why?"
          confirmText="Record decision"
          tone="primary"
          onConfirm={async (reason) => {
            onChange(await apiPost<BatchDetail>(`/api/batches/${batch.id}/disposition/`, { decision, reason, password }));
            close();
            toast("ok", "Decision recorded", "It is now the batch's status.");
          }}
          onClose={close}
        >
          <label className="field">
            Decision
            <select required value={decision} onChange={(e) => setDecision(e.target.value)}>
              <option value="">Choose</option>
              {disposition.choices.map((c) => (
                <option key={c.value} value={c.value} disabled={c.value === "RELEASED" && blocked}>{c.label}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Your password <span className="note">this is a signature</span>
            <input type="password" required autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </label>
        </CommentModal>
      )}
    </section>
  );
}
