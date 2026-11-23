import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { apiGet, apiPost } from "../../api";
import { useAuth } from "../../auth";
import { Message, TableSkeleton } from "../../components/Feedback";
import { useToast } from "../../components/Toast";
import type { Investigation, InvestigationOptions } from "../../types";
import { todayInput } from "../../util";

/**
 * Opens an investigation from a failed or unusual result, or records a
 * deviation. The result itself is never touched: the record only points at it.
 */
export default function NewInvestigation() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { can } = useAuth();
  const register = can("report.view") && can("report.open.deviations");
  const resultId = params.get("result") ?? "";
  const lockedKind = resultId ? (params.get("kind") ?? "OOS") : "DEVIATION";

  const [options, setOptions] = useState<InvestigationOptions | null>(null);
  const [form, setForm] = useState({
    classification: "", description: "", responsible_id: "", due_date: todayInput(), product_id: "", batch_no: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiGet<InvestigationOptions>("/api/investigations/options/")
      .then(setOptions)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load the form."));
  }, []);

  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await apiPost<Investigation>("/api/investigations/", {
        ...form, kind: lockedKind, result_id: resultId || undefined,
      });
      toast("ok", `${created.reference} opened`, "It is now on the register.");
      navigate(`/investigations/${created.id}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open it.");
      setBusy(false);
    }
  };

  const kindLabel = options?.kinds.find((k) => k.value === lockedKind)?.label ?? "";

  return (
    <>
      <div className="breadcrumb">
        {register
          ? <><Link to="/reports">Reports</Link> / <Link to="/reports/deviations">Deviations &amp; CAPA</Link></>
          : <>Deviations &amp; CAPA</>} / New
      </div>
      <div className="page-head">
        <h1>{resultId ? `Open an investigation: ${kindLabel.toLowerCase()}` : "Record a deviation"}</h1>
        <p className="sub">
          {resultId
            ? "The result stays exactly as it was entered. This record only says what is being done about it."
            : "Something happened that the procedure did not expect. Say what, and who is looking into it."}
        </p>
      </div>
      {error && <div style={{ marginBottom: 16 }}><Message kind="error">{error}</Message></div>}
      {!options ? (
        !error && <div className="card"><div className="card-body flush"><TableSkeleton rows={4} /></div></div>
      ) : (
        <div className="card">
          <div className="card-body">
            <form className="stack" onSubmit={(e) => void submit(e)}>
              <label className="field">
                What happened <span className="req" aria-hidden="true">*</span>
                <textarea required value={form.description} onChange={(e) => set("description", e.target.value)} />
              </label>
              <div className="form-row">
                <label className="field">
                  Responsible <span className="req" aria-hidden="true">*</span>
                  <select required value={form.responsible_id} onChange={(e) => set("responsible_id", e.target.value)}>
                    <option value="">Choose a person</option>
                    {options.people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                </label>
                <label className="field">
                  Due date <span className="req" aria-hidden="true">*</span>
                  <input type="date" required value={form.due_date} onChange={(e) => set("due_date", e.target.value)} />
                </label>
              </div>
              <div className="form-row">
                <label className="field">
                  Classification <span className="note">can be set later</span>
                  <select value={form.classification} onChange={(e) => set("classification", e.target.value)}>
                    <option value="">Not classified yet</option>
                    {options.classifications.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                  </select>
                </label>
              </div>
              {!resultId && (
                <div className="form-row">
                  <label className="field">
                    Product <span className="note">if it concerns one</span>
                    <select value={form.product_id} onChange={(e) => set("product_id", e.target.value)}>
                      <option value="">None</option>
                      {options.products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  </label>
                  <label className="field">
                    Batch / Lot <span className="note">if it concerns one</span>
                    <input value={form.batch_no} maxLength={60} onChange={(e) => set("batch_no", e.target.value)} />
                  </label>
                </div>
              )}
              <div className="actions-bar" style={{ justifyContent: "flex-end" }}>
                <button type="submit" className="primary" disabled={busy}>
                  {busy ? "Opening…" : resultId ? "Open investigation" : "Record deviation"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
