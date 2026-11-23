import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { apiGet, apiPatch } from "../../api";
import { Message, TableSkeleton } from "../../components/Feedback";
import { useToast } from "../../components/Toast";
import type { QualityRulesData } from "../../types";

/** What the lab requires after a failed result. The quality unit's decision, so a change needs a reason. */
export default function QualityRules() {
  const toast = useToast();
  const [rules, setRules] = useState<QualityRulesData | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet<QualityRulesData>("/api/quality-rules/").then(setRules).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Could not load the rules.");
    });
  }, []);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setRules(await apiPatch<QualityRulesData>("/api/quality-rules/", { ...rules, reason }));
      setReason("");
      toast("ok", "Rules saved", "The change is in the activity log with your reason.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    }
    setBusy(false);
  };

  const set = (patch: Partial<QualityRulesData>) => setRules((r) => (r ? { ...r, ...patch } : r));

  return (
    <>
      <div className="page-head">
        <h1>Quality rules</h1>
        <p className="sub">
          What must happen after a failed result. They apply to every sample from the moment they are saved.
        </p>
      </div>
      {error && <Message kind="error">{error}</Message>}
      {!rules ? (
        !error && <div className="card"><div className="card-body flush"><TableSkeleton rows={4} /></div></div>
      ) : (
        <form className="card" onSubmit={(e) => void save(e)}>
          <div className="card-head"><h2>After a failed result</h2></div>
          <div className="card-body stack">
            <label className="rule-row">
              <input type="checkbox" checked={rules.oos_investigation_required}
                onChange={(e) => set({ oos_investigation_required: e.target.checked })} />
              <span>
                <b>A failure needs an investigation.</b> Its laboratory finding comes before any retest, and it must
                close before any certificate is signed.
              </span>
            </label>
            <label className="rule-row">
              <input type="checkbox" checked={rules.oos_second_analyst}
                onChange={(e) => set({ oos_second_analyst: e.target.checked })} />
              <span>
                <b>A second analyst retests.</b> Whoever produced the first failure does not do the retest.
              </span>
            </label>
            <label className="rule-row">
              <input type="checkbox" checked={rules.oos_batch_block}
                onChange={(e) => set({ oos_batch_block: e.target.checked })} />
              <span>
                <b>A failure holds the whole batch.</b> An unresolved failure on one sample stops certificates for
                every sample of that batch. Applies while investigations are required.
              </span>
            </label>
            <label className="field" style={{ maxWidth: 260 }}>
              Retests allowed per test on a sample
              <input type="number" min={0} max={10} required value={rules.oos_max_retests}
                onChange={(e) => set({ oos_max_retests: Number(e.target.value) })} />
            </label>
            <label className="field">
              Why are these changing? <span className="note">your SOP or decision reference</span>
              <input required maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            <div className="actions-bar" style={{ justifyContent: "flex-end" }}>
              <button type="submit" className="primary" disabled={busy}>{busy ? "Saving…" : "Save rules"}</button>
            </div>
          </div>
        </form>
      )}
    </>
  );
}
