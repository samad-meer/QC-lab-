import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../../api";
import type { PersonRef } from "../../types";
import { Message } from "../Feedback";
import ModalBackdrop from "../ModalBackdrop";

interface Candidate extends PersonRef {
  role: string;
  is_me: boolean;
  /** How many of the chosen samples they are trained for. */
  can_take: number;
  /** How many of them they already hold. */
  holds: number;
  sections: string[];
}

interface Outcome {
  assigned: { id: number; sample_no: string }[];
  skipped: { id: number; sample_no: string; reason: string }[];
  to: PersonRef;
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/**
 * The testing of several samples, given to one analyst at once. Each sample is assigned
 * as on its own page; one that cannot go to them stays as it was, and says why.
 */
export default function BulkAssignModal({ ids, onDone, onClose }: {
  ids: number[];
  /** Called once the assignment is made, whatever came of each sample. */
  onDone: () => void;
  onClose: () => void;
}) {
  const [data, setData] = useState<{ open: number; people: Candidate[] } | null>(null);
  const [userId, setUserId] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    apiGet<{ open: number; people: Candidate[] }>(`/api/samples/assign-testing/candidates/?ids=${ids.join(",")}`)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load who can take them."));
  }, [ids]);

  const chosen = data?.people.find((p) => String(p.id) === userId);
  // Those they are trained for, less those they already hold.
  const willTake = chosen ? chosen.can_take - chosen.holds : 0;
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const done = await apiPost<Outcome>("/api/samples/assign-testing/", { sample_ids: ids, user_id: Number(userId), note });
      setOutcome(done);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not assign them.");
    } finally {
      setBusy(false);
    }
  };

  const describe = (p: Candidate) => {
    const parts = [p.can_take === ids.length ? "trained for all" : `trained for ${p.can_take} of ${ids.length}`];
    if (p.holds) parts.push(`holds ${p.holds} already`);
    return `${p.name}${p.is_me ? " (you)" : ""} — ${parts.join(", ")}`;
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Assign testing" onClick={(e) => e.stopPropagation()}>
        {outcome ? (
          <>
            <h3>{outcome.assigned.length ? `${plural(outcome.assigned.length, "sample")} assigned to ${outcome.to.name}` : "Nothing was assigned"}</h3>
            {outcome.assigned.length > 0 && (
              <p className="modal-sub">
                {outcome.assigned.map((a) => a.sample_no).join(", ")}. Each is on its own record with your note,
                and {outcome.to.name} has a notice for each.
              </p>
            )}
            {outcome.skipped.length > 0 && (
              <div className="bulk-skipped">
                <b>{plural(outcome.skipped.length, "sample")} left as {outcome.skipped.length === 1 ? "it was" : "they were"}</b>
                <ul>
                  {outcome.skipped.map((x) => (
                    <li key={x.id}><span className="mono">{x.sample_no || `#${x.id}`}</span> {x.reason}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="actions">
              <button className="primary" onClick={onClose}>Done</button>
            </div>
          </>
        ) : (
          <>
            <h3>Assign the testing of {plural(ids.length, "sample")}</h3>
            <p className="modal-sub">
              One analyst takes them all, as if each had been assigned on its own page. A sample they are not trained
              for, or that has moved on, is left as it was and listed with the reason.
            </p>
            {data && data.open < ids.length && (
              <Message kind="info">
                {plural(ids.length - data.open, "of the chosen samples is", "of the chosen samples are")} past testing
                and will be left as {ids.length - data.open === 1 ? "it is" : "they are"}.
              </Message>
            )}
            <label className="field">
              Analyst
              <select value={userId} onChange={(e) => setUserId(e.target.value)} autoFocus>
                <option value="">
                  {data === null ? "Loading…" : data.people.length ? "— choose —" : "No analyst is trained for these samples"}
                </option>
                {data?.people.map((p) => <option key={p.id} value={p.id}>{describe(p)}</option>)}
              </select>
            </label>
            {chosen && chosen.can_take < ids.length && (
              <p className="field-note warn-note">
                {chosen.name} is trained for {chosen.sections.join(", ") || "no section"}: {plural(ids.length - chosen.can_take, "sample")} will
                be left as {ids.length - chosen.can_take === 1 ? "it is" : "they are"}.
              </p>
            )}
            <label className="field">
              Note <span className="note">Optional. It goes with each sample.</span>
              <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Morning receipt, priority batch" />
            </label>
            {error && <Message kind="error">{error}</Message>}
            <div className="actions">
              <button className="ghost" onClick={onClose} disabled={busy}>Cancel</button>
              <button className="primary" onClick={() => void submit()} disabled={busy || !chosen || willTake === 0}>
                {busy ? "Assigning…" : chosen ? (willTake ? `Assign ${plural(willTake, "sample")}` : "They hold them already") : "Assign"}
              </button>
            </div>
          </>
        )}
      </div>
    </ModalBackdrop>
  );
}
