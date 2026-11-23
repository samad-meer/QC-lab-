import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../../api";
import type { CustodyChain } from "../../types";
import { fmtDate } from "../../util";
import CommentModal from "../CommentModal";
import { Message } from "../Feedback";
import Stamp from "../Stamp";
import { useToast } from "../Toast";

const BLANK = {
  action: "", location: "", quantity: "", from_person_id: "", to_person_id: "", retain_until: "", witness_id: "",
  password: "", witness_password: "",
};

function AddEntry({ sampleId, chain, onSaved, onClose }: {
  sampleId: number;
  chain: CustodyChain;
  onSaved: (next: CustodyChain) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState(BLANK);
  const set = (key: keyof typeof BLANK, value: string) => setForm((f) => ({ ...f, [key]: value }));
  const people = chain.people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>);
  const { action } = form;
  const destroying = action === "DESTROYED";

  return (
    <CommentModal
      title="Add custody entry"
      hint={destroying
        ? "Only a finished sample, once any retain-until date has passed. You and the witness each sign. This ends the chain."
        : "Entries are never changed. A mistake is put right by a new entry."}
      label="Note"
      optional
      tone="primary"
      confirmText={destroying ? "Record destruction" : "Add entry"}
      placeholder="Anything the next person should know."
      onConfirm={async (comment) => {
        onSaved(await apiPost<CustodyChain>(`/api/lab/samples/${sampleId}/custody/`, { ...form, comment }));
      }}
      onClose={onClose}
    >
      <div className="report-filters">
        <label className="field">
          What happened
          <select required value={action} onChange={(e) => set("action", e.target.value)}>
            <option value="">Choose</option>
            {chain.actions.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
          </select>
        </label>
        <label className="field">
          Location
          <input required={action === "STORED" || action === "RETAINED"} maxLength={120} value={form.location}
            onChange={(e) => set("location", e.target.value)} />
        </label>
        <label className="field">
          Quantity
          <input maxLength={60} value={form.quantity} onChange={(e) => set("quantity", e.target.value)} />
        </label>
        {(action === "RECEIVED" || action === "TRANSFERRED") && (
          <>
            <label className="field">
              From
              <select value={form.from_person_id} onChange={(e) => set("from_person_id", e.target.value)}>
                <option value="">{action === "TRANSFERRED" ? "You" : "Not a person here"}</option>
                {people}
              </select>
            </label>
            <label className="field">
              To
              <select required={action === "TRANSFERRED"} value={form.to_person_id}
                onChange={(e) => set("to_person_id", e.target.value)}>
                <option value="">{action === "TRANSFERRED" ? "Choose" : "Not a person here"}</option>
                {people}
              </select>
            </label>
          </>
        )}
        {action === "RETAINED" && (
          <label className="field">
            Retain until <span className="note">can be extended, never brought forward</span>
            <input type="date" required value={form.retain_until} onChange={(e) => set("retain_until", e.target.value)} />
          </label>
        )}
        {destroying && (
          <label className="field">
            Witness <span className="note">a different person</span>
            <select required value={form.witness_id} onChange={(e) => set("witness_id", e.target.value)}>
              <option value="">Choose</option>
              {people}
            </select>
          </label>
        )}
      </div>
      {destroying && (
        <div className="form-row">
          <label className="field">
            Your password <span className="note">this is a signature</span>
            <input type="password" required autoComplete="current-password" value={form.password}
              onChange={(e) => set("password", e.target.value)} />
          </label>
          <label className="field">
            The witness's password
            <input type="password" required autoComplete="off" value={form.witness_password}
              onChange={(e) => set("witness_password", e.target.value)} />
          </label>
        </div>
      )}
    </CommentModal>
  );
}

/** Who has held a sample, where it was kept, and how it ended. */
export default function CustodyCard({ sampleId }: { sampleId: number }) {
  const toast = useToast();
  const [chain, setChain] = useState<CustodyChain | null>(null);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      setChain(await apiGet<CustodyChain>(`/api/lab/samples/${sampleId}/custody/`));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the chain of custody.");
    }
  }, [sampleId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="card" aria-label="Chain of custody">
      <div className="card-head">
        <h2>Chain of custody</h2>
        {chain?.destroyed ? <span className="badge muted">Destroyed</span>
          : chain?.retain_until && <span className="hint">Retained until {fmtDate(chain.retain_until)}</span>}
        <div className="spacer" />
        {chain && (chain.can_add || chain.can_destroy) && (
          <button className="ghost small" onClick={() => setAdding(true)}>Add custody entry…</button>
        )}
      </div>
      <div className="card-body flush">
        {error ? (
          <div style={{ padding: 18 }}><Message kind="error">{error}</Message></div>
        ) : !chain || chain.entries.length === 0 ? (
          <p className="hint" style={{ padding: "16px 22px", margin: 0 }}>{chain ? "No custody entries yet." : "Loading…"}</p>
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr><th>What happened</th><th>Where</th><th>From / to</th><th>Quantity</th><th>Recorded</th><th>Note</th></tr>
              </thead>
              <tbody>
                {chain.entries.map((e) => (
                  <tr key={e.id}>
                    <td>
                      <span className="cell-title">{e.action_label}</span>
                      {e.retain_until && <div className="cell-sub">Until {fmtDate(e.retain_until)}</div>}
                      {e.witness && <div className="cell-sub">Witness: {e.witness.name}</div>}
                    </td>
                    <td>{e.location || "—"}</td>
                    <td>{[e.from_person?.name, e.to_person?.name].filter(Boolean).join(" → ") || "—"}</td>
                    <td>{e.quantity || "—"}</td>
                    <td><Stamp at={e.at} by={e.by} /></td>
                    <td>{e.note || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {adding && chain && (
        <AddEntry
          sampleId={sampleId}
          chain={chain}
          onSaved={(next) => {
            setChain(next);
            setAdding(false);
            toast("ok", "Custody entry added", "It is on the sample's chain.");
          }}
          onClose={() => setAdding(false)}
        />
      )}
    </section>
  );
}
