import { useEffect, useState } from "react";
import { apiGet, apiPut } from "../api";
import type { BatchNumberRuleView } from "../types";
import { Message } from "./Feedback";
import Field from "./Field";
import { useToast } from "./Toast";

/** How internal batch IDs are built. The official number is never touched. */
export default function BatchNumbering() {
  const toast = useToast();
  const [rule, setRule] = useState<BatchNumberRuleView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet<BatchNumberRuleView>("/api/batch-numbering/")
      .then(setRule)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load the rule."));
  }, []);

  if (!rule) return error ? <Message kind="error">{error}</Message> : null;
  const set = (patch: Partial<BatchNumberRuleView>) => setRule({ ...rule, ...patch });

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      setRule(await apiPut<BatchNumberRuleView>("/api/batch-numbering/", rule));
      toast("ok", "Numbering rule saved", "It applies to batches recorded from now on.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the rule.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="card-head">
        <h2>Internal batch IDs</h2>
        <span className="hint">The official batch number is never generated or changed</span>
      </div>
      <div className="card-body stack">
        <div className="form-row three">
          <Field label="Prefix" required>
            <input value={rule.prefix} onChange={(e) => set({ prefix: e.target.value })} />
          </Field>
          <Field label="Separator">
            <select value={rule.separator} onChange={(e) => set({ separator: e.target.value })}>
              <option value="-">Dash ( - )</option>
              <option value="/">Slash ( / )</option>
              <option value=".">Dot ( . )</option>
              <option value="">None</option>
            </select>
          </Field>
          <Field label="Digits in the number">
            <input type="number" min={3} max={10} value={rule.digits} onChange={(e) => set({ digits: Number(e.target.value) })} />
          </Field>
        </div>
        <div className="option-grid">
          <label className="cl-flag">
            <input type="checkbox" checked={rule.include_year} onChange={(e) => set({ include_year: e.target.checked })} />
            Include the year
          </label>
          <label className="cl-flag">
            <input type="checkbox" checked={rule.include_section} onChange={(e) => set({ include_section: e.target.checked })} />
            Include the section
          </label>
          <label className="cl-flag">
            <input type="checkbox" checked={rule.include_product} onChange={(e) => set({ include_product: e.target.checked })} />
            Include the product code
          </label>
          <label className="cl-flag">
            <input type="checkbox" checked={rule.restart_yearly} onChange={(e) => set({ restart_yearly: e.target.checked })} />
            Start again from 1 each year
          </label>
        </div>
        {error && <Message kind="error">{error}</Message>}
        <div className="actions-bar">
          <span className="cell-sub">Saved rule looks like <span className="mono">{rule.example}</span>. Numbers already issued never change or repeat.</span>
          <div className="spacer" />
          <button className="primary small" disabled={busy || !rule.prefix.trim()} onClick={() => void save()}>
            {busy ? "Saving…" : "Save rule"}
          </button>
        </div>
      </div>
    </div>
  );
}
