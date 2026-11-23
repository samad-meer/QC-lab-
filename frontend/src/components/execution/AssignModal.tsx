import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../../api";
import type { Candidate, Execution, StepView } from "../../types";
import { Message } from "../Feedback";
import ModalBackdrop from "../ModalBackdrop";

/**
 * Assign a step to someone (needs sample.assign), or hand your own step
 * over. Only people the server would accept are offered.
 */
export default function AssignModal({
  sampleId,
  step,
  mode,
  onDone,
  onClose,
}: {
  sampleId: number;
  step: StepView;
  mode: "assign" | "handover";
  onDone: (e: Execution) => void;
  onClose: () => void;
}) {
  const [people, setPeople] = useState<Candidate[] | null>(null);
  const [userId, setUserId] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiGet<Candidate[]>(`/api/samples/${sampleId}/candidates/?step=${encodeURIComponent(step.key)}`)
      .then(setPeople)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load who can take this."));
  }, [sampleId, step.key]);

  const handover = mode === "handover";
  const options = (people ?? []).filter((p) => !(handover && p.is_me) && p.id !== step.holder?.id);

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      onDone(await apiPost<Execution>(`/api/samples/${sampleId}/assignments/`, {
        mode, step: step.key, user_id: Number(userId), note,
      }));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={handover ? "Hand over" : "Assign"} onClick={(e) => e.stopPropagation()}>
        <h3>{handover ? `Hand over “${step.name}”` : `${step.holder ? "Reassign" : "Assign"} “${step.name}”`}</h3>
        <p className="modal-sub">
          {handover
            ? "The work stays with you until they accept it. If they decline, you will see their reason."
            : step.requires_acceptance
              ? "This step must be accepted: the person you choose has to accept it before they can work on it."
              : "The person you choose holds the step straight away."}
        </p>
        <label className="field">
          {step.kind === "testing" ? "Analyst (trained for this section)" : `Someone in the ${step.role_name} role`}
          <select value={userId} onChange={(e) => setUserId(e.target.value)} autoFocus>
            <option value="">{people === null ? "Loading…" : options.length ? "— choose —" : "Nobody else is eligible"}</option>
            {options.map((p) => (
              <option key={p.id} value={p.id}>{p.name}{p.is_me ? " (you)" : ""} — {p.role}</option>
            ))}
          </select>
        </label>
        <label className="field">
          {handover ? "Handover note" : "Note"}{" "}
          <span className="note">{handover ? "Required — what the next person needs to know." : "Optional."}</span>
          <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)}
            placeholder={handover ? "e.g. Assay prep done; HPLC run 3 still to inject." : ""} />
        </label>
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="primary" onClick={() => void submit()} disabled={busy || !userId || (handover && !note.trim())}>
            {busy ? "Saving…" : handover ? "Hand over" : "Assign"}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}
