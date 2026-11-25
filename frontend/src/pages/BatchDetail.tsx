import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet, apiPost, apiUpload } from "../api";
import BatchModal from "../components/BatchModal";
import BatchProgress from "../components/BatchProgress";
import BatchStages from "../components/BatchStages";
import CommentModal from "../components/CommentModal";
import { FileRow } from "../components/execution/Documents";
import { EmptyState, Message, TableSkeleton } from "../components/Feedback";
import Field from "../components/Field";
import DispositionCard from "../components/lab/DispositionCard";
import SampleTable from "../components/SampleTable";
import Stamp from "../components/Stamp";
import { OutcomeBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import PrintLinks from "../components/PrintLinks";
import type { BatchDetail, BatchDocumentView } from "../types";
import { fmtDate, fmtDateTime } from "../util";

function Documents({ batch, onChange }: { batch: BatchDetail; onChange: (b: BatchDetail) => void }) {
  const [docType, setDocType] = useState(batch.document_types[0]?.key ?? "OTHER");
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showOld, setShowOld] = useState(false);
  const [withdrawing, setWithdrawing] = useState<BatchDocumentView | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const replacing = useRef<BatchDocumentView | null>(null);

  const current = batch.documents.filter((d) => d.is_current);
  const old = batch.documents.filter((d) => !d.is_current);

  const upload = async (file: File) => {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("doc_type", docType);
      form.append("title", title);
      if (replacing.current) form.append("replaces_id", String(replacing.current.id));
      onChange(await apiUpload<BatchDetail>(`/api/batches/${batch.id}/documents/`, form));
      setTitle("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
      replacing.current = null;
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const pick = (d: BatchDocumentView | null) => {
    replacing.current = d;
    fileRef.current?.click();
  };

  const row = (d: BatchDocumentView, live: boolean) => (
    <FileRow key={d.id} a={d} label={d.doc_type_label} canReplace={live && batch.can_manage}
      canWithdraw={live && batch.can_manage} onReplace={() => pick(d)} onWithdraw={() => setWithdrawing(d)} />
  );

  return (
    <div className="card">
      <div className="card-head">
        <h2>Batch documents</h2>
        <span className="hint">{current.length} current · never deleted, only replaced or withdrawn</span>
      </div>
      <div className="card-body">
        <input ref={fileRef} type="file" hidden onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void upload(f);
        }} />
        {current.length === 0 && old.length === 0 ? (
          <EmptyState icon="▢" title="No documents yet" sub="Batch records, specifications and supplier certificates kept against this batch appear here." />
        ) : (
          <ul className="file-list">{current.map((d) => row(d, true))}</ul>
        )}
        {old.length > 0 && (
          <>
            <button type="button" className="link-btn" onClick={() => setShowOld((v) => !v)} aria-expanded={showOld}>
              {showOld ? "Hide" : "Show"} {old.length} earlier or withdrawn version{old.length === 1 ? "" : "s"}
            </button>
            {showOld && <ul className="file-list">{old.map((d) => row(d, false))}</ul>}
          </>
        )}
        {error && <div style={{ marginTop: 10 }}><Message kind="error">{error}</Message></div>}
        {batch.can_manage && (
          <div className="form-row" style={{ marginTop: 14, alignItems: "end" }}>
            <Field label="Kind of document">
              <select value={docType} onChange={(e) => setDocType(e.target.value)}>
                {batch.document_types.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
              </select>
            </Field>
            <Field label="Title" hint="Leave blank to use the file's name">
              <div className="actions-bar" style={{ flexWrap: "nowrap" }}>
                <input value={title} onChange={(e) => setTitle(e.target.value)} />
                <button className="ghost small" style={{ whiteSpace: "nowrap" }} disabled={busy} onClick={() => pick(null)}>
                  {busy ? "Uploading…" : "+ Upload"}
                </button>
              </div>
            </Field>
          </div>
        )}
      </div>
      {withdrawing && (
        <CommentModal
          title={`Withdraw ${withdrawing.title}`}
          hint="The document stays on record, marked withdrawn, with your reason."
          label="Why is it being withdrawn?"
          confirmText="Withdraw the document"
          onConfirm={async (reason) => {
            onChange(await apiPost<BatchDetail>(`/api/batch-documents/${withdrawing.id}/withdraw/`, { reason }));
            setWithdrawing(null);
          }}
          onClose={() => setWithdrawing(null)}
        />
      )}
    </div>
  );
}

/** One batch and everything that hangs off it: the trace from product to certificate. */
export default function BatchDetailPage() {
  const { id } = useParams();
  const toast = useToast();
  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);

  const load = useCallback(async () => {
    try {
      setBatch(await apiGet<BatchDetail>(`/api/batches/${id}/`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this batch.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <Message kind="error">{error}</Message>;
  if (!batch) return <div className="card"><div className="card-body flush"><TableSkeleton /></div></div>;

  return (
    <>
      <div className="breadcrumb"><Link to="/batches">Batches</Link> / {batch.internal_id}</div>
      <div className="page-head">
        <h1>{batch.official_batch_no}</h1>
        <p className="sub">
          {batch.product.name} ({batch.product.code}) · internal ID <span className="mono">{batch.internal_id}</span>
        </p>
      </div>

      <BatchProgress batch={batch} />

      <div className="card">
        <div className="card-head">
          <h2>Batch details</h2>
          <div className="spacer" />
          <div className="actions-bar">
            <PrintLinks items={[
              { label: "Label", icon: "label", href: `/api/batches/${batch.id}/label/`, hint: "The batch label, to stick on the container." },
              { label: "Batch record", icon: "record", href: `/api/batches/${batch.id}/record/`,
                hint: "The whole batch record: details, QC stages, values and signatures." },
            ]} />
            {batch.can_manage && (
              <button className="ghost small" onClick={() => setEditing(true)}>
                <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z" /><path d="M13.5 6.5l4 4" /></svg>
                Correct…
              </button>
            )}
          </div>
        </div>
        <div className="card-body">
          <div className="kv">
            <div><div className="k">Official batch number</div><div className="v">{batch.official_batch_no}</div></div>
            <div><div className="k">Internal ID</div><div className="v mono">{batch.internal_id}</div></div>
            <div>
              <div className="k">Product</div>
              <div className="v"><Link to={`/batches?product=${batch.product.id}`}>{batch.product.name}</Link></div>
            </div>
            <div>
              <div className="k">Dosage form · strength</div>
              <div className="v">{[batch.product.dosage_form, batch.product.strength].filter(Boolean).join(" · ") || "—"}</div>
            </div>
            <div><div className="k">Manufacturing site</div><div className="v">{batch.manufacturing_site || "—"}</div></div>
            <div><div className="k">Date of manufacture</div><div className="v">{batch.manufacturing_date ? fmtDate(batch.manufacturing_date) : "—"}</div></div>
            <div><div className="k">Expiry / retest</div><div className="v">{batch.expiry_date ? fmtDate(batch.expiry_date) : "—"}</div></div>
            <div><div className="k">Batch size</div><div className="v">{batch.batch_size || "—"}</div></div>
            {batch.notes && <div style={{ gridColumn: "span 2" }}><div className="k">Notes</div><div className="v">{batch.notes}</div></div>}
          </div>
          <div className="cell-sub" style={{ marginTop: 12 }}>
            <Stamp at={batch.created_at} verb="Recorded" />{batch.created_by ? ` by ${batch.created_by}` : " from existing samples"}
          </div>
        </div>
      </div>

      <BatchStages batch={batch} onChange={setBatch} />
      <DispositionCard batch={batch} onChange={setBatch} />

      <div className="card">
        <div className="card-head"><h2>Samples</h2><span className="hint">{batch.sample_count}</span></div>
        <div className="card-body flush">
          {batch.samples.length === 0 ? (
            <EmptyState title="No samples yet" sub="Samples of this batch appear here once registered." />
          ) : (
            <SampleTable samples={batch.samples} />
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>Test results</h2><span className="hint">Current results across the samples above</span></div>
        <div className="card-body flush">
          {batch.results.length === 0 ? (
            <EmptyState title="No results yet" />
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead><tr><th>Sample</th><th>Test</th><th>Limit</th><th>Result</th><th>Outcome</th><th>Entered</th></tr></thead>
                <tbody>
                  {batch.results.map((r) => (
                    <tr key={r.id}>
                      <td className="num"><Link to={`/samples/${r.sample_id}`}>{r.sample_no}</Link></td>
                      <td className="cell-title">{r.test}</td>
                      <td>{r.limit_text}</td>
                      <td className="num">{r.value}{r.unit ? ` ${r.unit}` : ""}</td>
                      <td><OutcomeBadge outcome={r.outcome} /></td>
                      <td>{r.entered_by}<div className="cell-sub">{fmtDateTime(r.entered_at)}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>Certificates</h2></div>
        <div className="card-body flush">
          {batch.certificates.length === 0 ? (
            <EmptyState title="No certificates yet" sub="One is created the moment an analyst signs." />
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead><tr><th>Sample</th><th>Certificate</th><th>Conclusion</th><th>Status</th><th>Created</th></tr></thead>
                <tbody>
                  {batch.certificates.map((c) => (
                    <tr key={c.id}>
                      <td className="num"><Link to={`/samples/${c.sample_id}`}>{c.sample_no}</Link></td>
                      <td><Link to={`/certificates/${c.id}`}>Version {c.version}</Link></td>
                      <td>{c.overall}</td>
                      <td><span className="badge muted">{c.status_label}</span></td>
                      <td>{fmtDateTime(c.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <Documents batch={batch} onChange={setBatch} />

      <div className="card">
        <div className="card-head"><h2>History</h2></div>
        <div className="card-body">
          {batch.history.length === 0 ? (
            <div className="cell-sub">Nothing recorded for this batch yet.</div>
          ) : (
            <ul className="timeline">
              {batch.history.map((e) => (
                <li key={e.id}>
                  <span className="when">{fmtDateTime(e.at)}</span>
                  <span><b>{e.actor_name}</b> {e.sentence}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {editing && (
        <BatchModal
          editing={batch}
          onDone={(updated) => {
            setBatch(updated);
            toast("ok", "Batch corrected", "The reason and the old values are on the record.");
          }}
          onClose={() => setEditing(false)}
        />
      )}
    </>
  );
}
