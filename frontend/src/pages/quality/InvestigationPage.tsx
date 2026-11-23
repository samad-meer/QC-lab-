import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet, apiPatch, apiPost } from "../../api";
import { useAuth } from "../../auth";
import CommentModal from "../../components/CommentModal";
import { Message, TableSkeleton } from "../../components/Feedback";
import SignModal from "../../components/SignModal";
import Stamp from "../../components/Stamp";
import { OutcomeBadge } from "../../components/StatusBadge";
import { useToast } from "../../components/Toast";
import type { CapaActionView, Investigation, InvestigationOptions } from "../../types";
import { fmtDate, todayInput } from "../../util";

const TONES: Record<string, string> = { OPEN: "warn", PENDING_CLOSURE: "hot", CLOSED: "pass" };

function EditForm({ inv, options, onSaved, onCancel }: {
  inv: Investigation;
  options: InvestigationOptions;
  onSaved: (next: Investigation) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState({
    description: inv.description, classification: inv.classification, root_cause: inv.root_cause,
    outcome: inv.outcome, conclusion: inv.conclusion, responsible_id: String(inv.responsible.id),
    due_date: inv.due_date, reason: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSaved(await apiPatch<Investigation>(`/api/investigations/${inv.id}/`, form));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
      setBusy(false);
    }
  };

  return (
    <form className="stack" onSubmit={(e) => void submit(e)}>
      {error && <Message kind="error">{error}</Message>}
      <label className="field">
        What happened
        <textarea required value={form.description} onChange={(e) => set("description", e.target.value)} />
      </label>
      <label className="field">
        Root cause <span className="note">or that none was established</span>
        <textarea value={form.root_cause} onChange={(e) => set("root_cause", e.target.value)} />
      </label>
      <label className="field">
        Final outcome <span className="note">as decided under the lab's investigation procedure</span>
        <textarea value={form.outcome} onChange={(e) => set("outcome", e.target.value)} />
      </label>
      {inv.kind === "OOS" && (
        <label className="field">
          Conclusion <span className="note">only a laboratory error invalidates a failure</span>
          <select value={form.conclusion} onChange={(e) => set("conclusion", e.target.value)}>
            <option value="">Not concluded yet</option>
            {options.conclusions.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </label>
      )}
      <div className="form-row">
        <label className="field">
          Classification
          <select value={form.classification} onChange={(e) => set("classification", e.target.value)}>
            <option value="">Not classified yet</option>
            {options.classifications.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </label>
        <label className="field">
          Responsible
          <select value={form.responsible_id} onChange={(e) => set("responsible_id", e.target.value)}>
            {options.people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
      </div>
      <div className="form-row">
        <label className="field">
          Due date
          <input type="date" required value={form.due_date} onChange={(e) => set("due_date", e.target.value)} />
        </label>
        <label className="field">
          Reason for the change <span className="note">needed when changing what was recorded</span>
          <input value={form.reason} maxLength={500} onChange={(e) => set("reason", e.target.value)} />
        </label>
      </div>
      <div className="actions-bar" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="subtle" onClick={onCancel}>Cancel</button>
        <button type="submit" className="primary" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
      </div>
    </form>
  );
}

function LabFindingForm({ inv, options, onSaved, onCancel }: {
  inv: Investigation;
  options: InvestigationOptions;
  onSaved: (next: Investigation) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState({ finding: inv.lab_finding, notes: inv.lab_finding_notes, reason: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSaved(await apiPost<Investigation>(`/api/investigations/${inv.id}/lab-finding/`, form));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
      setBusy(false);
    }
  };

  return (
    <form className="stack" onSubmit={(e) => void submit(e)}>
      {error && <Message kind="error">{error}</Message>}
      <label className="field">
        What did the laboratory investigation find?
        <select required value={form.finding} onChange={(e) => set("finding", e.target.value)}>
          <option value="">Choose</option>
          {options.lab_findings.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
        </select>
      </label>
      <label className="field">
        What was checked <span className="note">calculations, preparations, instrument, standards, raw data</span>
        <textarea required value={form.notes} onChange={(e) => set("notes", e.target.value)} />
      </label>
      {inv.lab_finding && (
        <label className="field">
          Reason for the change
          <input required maxLength={500} value={form.reason} onChange={(e) => set("reason", e.target.value)} />
        </label>
      )}
      <div className="actions-bar" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="subtle" onClick={onCancel}>Cancel</button>
        <button type="submit" className="primary" disabled={busy}>{busy ? "Saving…" : "Save finding"}</button>
      </div>
    </form>
  );
}

function AddAction({ inv, options, onSaved }: {
  inv: Investigation;
  options: InvestigationOptions;
  onSaved: (next: Investigation) => void;
}) {
  const blank = { kind: "CORRECTIVE", description: "", owner_id: "", due_date: todayInput() };
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSaved(await apiPost<Investigation>(`/api/investigations/${inv.id}/actions/`, form));
      setForm(blank);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add the action.");
    }
    setBusy(false);
  };

  return (
    <form className="stack report-action-form" onSubmit={(e) => void submit(e)}>
      {error && <Message kind="error">{error}</Message>}
      <div className="report-filters">
        <label className="field">
          Type
          <select value={form.kind} onChange={(e) => set("kind", e.target.value)}>
            {options.action_kinds.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
        </label>
        <label className="field">
          Owner
          <select required value={form.owner_id} onChange={(e) => set("owner_id", e.target.value)}>
            <option value="">Choose a person</option>
            {options.people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label className="field">
          Due
          <input type="date" required value={form.due_date} onChange={(e) => set("due_date", e.target.value)} />
        </label>
      </div>
      <label className="field">
        Action
        <input required maxLength={1000} value={form.description} onChange={(e) => set("description", e.target.value)} />
      </label>
      <div className="actions-bar" style={{ justifyContent: "flex-end" }}>
        <button type="submit" className="ghost small" disabled={busy}>Add action</button>
      </div>
    </form>
  );
}

/** One investigation or deviation: what it concerns, what was found, and who closed it. */
export default function InvestigationPage() {
  const { id = "" } = useParams();
  const { can } = useAuth();
  const toast = useToast();
  const [inv, setInv] = useState<Investigation | null>(null);
  const [options, setOptions] = useState<InvestigationOptions | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [completing, setCompleting] = useState<CapaActionView | null>(null);
  const [verifying, setVerifying] = useState<CapaActionView | null>(null);
  const [password, setPassword] = useState("");
  const [closing, setClosing] = useState(false);
  const [returning, setReturning] = useState(false);
  const [finding, setFinding] = useState(false);

  const load = useCallback(async () => {
    try {
      setInv(await apiGet<Investigation>(`/api/investigations/${id}/`));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this record.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const manages = can("investigation.manage");
  // Its register and the sample's history are reports; without them, plain words and the sample's own page.
  const register = can("report.view") && can("report.open.deviations");
  const history = can("report.view") && can("report.open.sample-register");
  const crumb = register ? <Link to="/reports/deviations">Deviations &amp; CAPA</Link> : <>Deviations &amp; CAPA</>;
  useEffect(() => {
    if (manages) apiGet<InvestigationOptions>("/api/investigations/options/").then(setOptions).catch(() => undefined);
  }, [manages]);

  if (error && !inv) {
    return (
      <>
        <div className="breadcrumb">{crumb}</div>
        <Message kind="error">{error}</Message>
      </>
    );
  }
  if (!inv) return <div className="card"><div className="card-body flush"><TableSkeleton rows={6} /></div></div>;

  const send = async () => {
    try {
      setInv(await apiPost<Investigation>(`/api/investigations/${inv.id}/submit/`));
      toast("ok", "Sent for closure approval", "Someone independent will review it.");
    } catch (err) {
      toast("error", "Could not send it for closure", err instanceof Error ? err.message : "");
    }
  };

  return (
    <>
      <div className="breadcrumb">
        {register && <><Link to="/reports">Reports</Link> / </>}{crumb} / {inv.reference}
      </div>
      <div className="page-head">
        <h1>{inv.reference}</h1>
        <p className="sub">
          {inv.kind_label} <span className={`badge ${TONES[inv.status]}`}>{inv.status_label}</span>
          {inv.classification_label && <> <span className="badge muted">{inv.classification_label}</span></>}
        </p>
      </div>

      <section className="card" aria-label="The record">
        <div className="card-head">
          <h2>The record</h2>
          <div className="spacer" />
          {inv.can.edit && options && !editing && (
            <button className="ghost small" onClick={() => setEditing(true)}>Edit…</button>
          )}
        </div>
        <div className="card-body doc-parts">
          {editing && options ? (
            <EditForm
              inv={inv}
              options={options}
              onSaved={(next) => {
                setInv(next);
                setEditing(false);
                toast("ok", "Saved", "The change is on the record.");
              }}
              onCancel={() => setEditing(false)}
            />
          ) : (
            <>
              <div className="kv">
                <div>
                  <div className="k">Sample</div>
                  <div className="v">
                    {inv.sample
                      ? <Link to={history ? `/reports/sample-history/${inv.sample.id}` : `/samples/${inv.sample.id}`}>
                          {inv.sample.sample_no}
                        </Link>
                      : "—"}
                  </div>
                </div>
                <div><div className="k">Test</div><div className="v">{inv.test_name || "—"}</div></div>
                <div><div className="k">Product</div><div className="v">{inv.product_name || "—"}</div></div>
                <div><div className="k">Batch / Lot</div><div className="v">{inv.batch_no || "—"}</div></div>
                <div><div className="k">Responsible</div><div className="v">{inv.responsible.name}</div></div>
                <div><div className="k">Due</div><div className="v">{fmtDate(inv.due_date)}</div></div>
                <div><div className="k">Opened by</div><div className="v">{inv.opened_by.name}</div></div>
                <div><div className="k">Closure approved by</div><div className="v">{inv.closed_by?.name ?? "—"}</div></div>
              </div>
              <div>
                <div className="kv-label">What happened</div>
                <p className="kv-text">{inv.description}</p>
              </div>
              <div>
                <div className="kv-label">Root cause</div>
                <p className="kv-text">{inv.root_cause || "Not recorded yet."}</p>
              </div>
              <div>
                <div className="kv-label">Final outcome</div>
                <p className="kv-text">{inv.outcome || "Not recorded yet."}</p>
              </div>
              {inv.kind === "OOS" && (
                <div>
                  <div className="kv-label">Conclusion</div>
                  <p className="kv-text">{inv.conclusion_label || "Not concluded yet."}</p>
                </div>
              )}
            </>
          )}
        </div>
      </section>

      {inv.failure && (
        <section className="card" aria-label="The failure">
          <div className="card-head">
            <h2>The failure and everything since</h2>
            <span className="hint">Limit: {inv.failure.limit}</span>
          </div>
          <div className="card-body flush">
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr><th>Result</th><th>Outcome</th><th>Entered</th><th>Retest</th><th /></tr>
                </thead>
                <tbody>
                  {inv.failure.results.map((r) => (
                    <tr key={r.id}>
                      <td className="num">{r.value}{inv.failure?.unit ? ` ${inv.failure.unit}` : ""}</td>
                      <td><OutcomeBadge outcome={r.outcome} /></td>
                      <td><Stamp at={r.entered_at} by={r.entered_by} /></td>
                      <td>
                        {r.retest_kind
                          ? <>{r.retest_kind}<div className="cell-sub">Authorized by {r.authorized_by?.name}</div></>
                          : "Original"}
                      </td>
                      <td>{r.current ? <span className="badge muted">Current</span> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      {inv.kind === "OOS" && (
        <section className="card" aria-label="Laboratory investigation">
          <div className="card-head">
            <h2>Laboratory investigation</h2>
            <span className="hint">Comes before any retest</span>
            <div className="spacer" />
            {inv.can.lab_finding && options && !finding && (
              <button className="ghost small" onClick={() => setFinding(true)}>
                {inv.lab_finding ? "Change…" : "Record finding…"}
              </button>
            )}
          </div>
          <div className="card-body doc-parts">
            {finding && options ? (
              <LabFindingForm
                inv={inv}
                options={options}
                onSaved={(next) => {
                  setInv(next);
                  setFinding(false);
                  toast("ok", "Finding recorded", "A retest can now be requested, within the lab's limit.");
                }}
                onCancel={() => setFinding(false)}
              />
            ) : inv.lab_finding ? (
              <div>
                <div className="kv-label">{inv.lab_finding_label}</div>
                <p className="kv-text">{inv.lab_finding_notes}</p>
                <span className="hint"><Stamp at={inv.lab_finding_at} by={inv.lab_finding_by} /></span>
              </div>
            ) : (
              <p className="hint" style={{ margin: 0 }}>Not recorded yet. No retest can be requested until it is.</p>
            )}
          </div>
        </section>
      )}

      <section className="card" aria-label="Corrective and preventive actions">
        <div className="card-head">
          <h2>Corrective and preventive actions</h2>
          <span className="hint">Completed once, verified by someone else, never removed</span>
        </div>
        <div className="card-body flush">
          {inv.actions.length === 0 ? (
            <p className="hint" style={{ padding: "16px 22px", margin: 0 }}>No actions yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr><th>Type</th><th>Action</th><th>Owner</th><th>Due</th><th>Completed</th><th>Verified</th></tr>
                </thead>
                <tbody>
                  {inv.actions.map((a) => (
                    <tr key={a.id}>
                      <td>{a.kind_label}</td>
                      <td>{a.description}</td>
                      <td>{a.owner.name}</td>
                      <td>{fmtDate(a.due_date)}</td>
                      <td>
                        {a.completed_at ? (
                          <>
                            <Stamp at={a.completed_at} by={a.completed_by} />
                            <div className="cell-sub">“{a.completion_note}”</div>
                          </>
                        ) : a.can_complete ? (
                          <button className="ghost small" onClick={() => setCompleting(a)}>Complete…</button>
                        ) : "Open"}
                      </td>
                      <td>
                        {a.verified_at ? (
                          <>
                            <Stamp at={a.verified_at} by={a.verified_by} />
                            <div className="cell-sub">“{a.verification_note}”</div>
                          </>
                        ) : a.can_verify ? (
                          <button className="ghost small" onClick={() => setVerifying(a)}>Verify…</button>
                        ) : a.completed_at ? "Not verified" : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {inv.can.edit && options && (
          <div className="card-body" style={{ borderTop: "1px solid var(--line)" }}>
            <AddAction inv={inv} options={options} onSaved={setInv} />
          </div>
        )}
      </section>

      {inv.status !== "CLOSED" && (
        <section className="card" aria-label="Closure">
          <div className="card-head"><h2>Closure</h2></div>
          <div className="card-body doc-parts">
            {inv.status === "OPEN" && (
              <div className="actions-bar">
                <span className="hint">
                  {inv.kind === "OOS"
                    ? "Needs the laboratory finding, a classification, root cause, final outcome and conclusion, with every action completed and verified."
                    : "Needs a classification, root cause and final outcome, with every action completed and verified."}
                </span>
                <div className="spacer" />
                {inv.can.edit && <button className="primary small" onClick={() => void send()}>Send for closure approval</button>}
              </div>
            )}
            {inv.status === "PENDING_CLOSURE" && (
              <div className="actions-bar">
                <span className="hint">
                  <Stamp at={inv.submitted_at} by={inv.submitted_by} verb="Sent by" />
                </span>
                <div className="spacer" />
                {inv.can.approve && (
                  <>
                    <button className="danger small" onClick={() => setReturning(true)}>Send back…</button>
                    <button className="primary small" onClick={() => setClosing(true)}>Approve closure…</button>
                  </>
                )}
              </div>
            )}
            {inv.can.approve_blocked && (
              <Message kind="info">
                You took part in this work, so someone independent must approve its closure.
              </Message>
            )}
          </div>
        </section>
      )}

      <section className="card" aria-label="History">
        <div className="card-head"><h2>History</h2><span className="hint">Every change, with the old and new values</span></div>
        <div className="card-body">
          <ul className="timeline">
            {inv.events.map((e) => (
              <li key={e.id}>
                <span className="when"><Stamp at={e.at} /></span>
                <span>
                  <b>{e.actor.name}</b> {e.what.toLowerCase()}
                  {e.changes.map((c) => (
                    <span className="comment" key={c.field}>
                      {c.field}: “{c.old || "blank"}” to “{c.new || "blank"}”
                    </span>
                  ))}
                  {e.comment && <span className="comment">“{e.comment}”</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {completing && (
        <CommentModal
          title="Complete this action"
          hint={completing.description}
          label="What was done?"
          confirmText="Complete action"
          tone="primary"
          onConfirm={async (note) => {
            setInv(await apiPost<Investigation>(
              `/api/investigations/${inv.id}/actions/${completing.id}/complete/`, { note },
            ));
            setCompleting(null);
          }}
          onClose={() => setCompleting(null)}
        />
      )}
      {verifying && (
        <CommentModal
          title="Verify this action"
          hint={`${verifying.description} Someone other than its owner, and whoever completed it, confirms that it worked.`}
          label="How did you check that it worked?"
          confirmText="Verify action"
          tone="primary"
          onConfirm={async (note) => {
            setInv(await apiPost<Investigation>(
              `/api/investigations/${inv.id}/actions/${verifying.id}/verify/`, { note, password },
            ));
            setVerifying(null);
            setPassword("");
            toast("ok", "Action verified", "It is on the record with your name.");
          }}
          onClose={() => {
            setVerifying(null);
            setPassword("");
          }}
        >
          <label className="field">
            Your password <span className="note">this is a signature</span>
            <input type="password" required autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </label>
        </CommentModal>
      )}
      {returning && (
        <CommentModal
          title={`Send ${inv.reference} back`}
          label="What still needs doing?"
          confirmText="Send back"
          onConfirm={async (comment) => {
            setInv(await apiPost<Investigation>(`/api/investigations/${inv.id}/return/`, { comment }));
            setReturning(false);
          }}
          onClose={() => setReturning(false)}
        />
      )}
      {closing && (
        <SignModal
          title={`Approve the closure of ${inv.reference}`}
          meaning="Closure approved by"
          description="Once closed, this record can never be changed. Nothing here changes any result."
          onConfirm={async (password) => {
            setInv(await apiPost<Investigation>(`/api/investigations/${inv.id}/close/`, { password }));
            setClosing(false);
            toast("ok", `${inv.reference} closed`, "It is on the register as closed.");
          }}
          onClose={() => setClosing(false)}
        />
      )}
    </>
  );
}
