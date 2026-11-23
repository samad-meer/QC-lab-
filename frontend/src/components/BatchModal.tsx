import { useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost } from "../api";
import type { BatchDetail, BatchRow, Page, ProductMasterRow } from "../types";
import { Message } from "./Feedback";
import Field from "./Field";
import ModalBackdrop from "./ModalBackdrop";

const BLANK = {
  product_id: "", official_batch_no: "", manufacturing_site: "", manufacturing_date: "",
  expiry_date: "", batch_size: "", notes: "",
};

/** Record a new batch, or correct one with a reason. The internal ID is never typed. */
export default function BatchModal({
  editing,
  onDone,
  onClose,
}: {
  editing?: BatchRow;
  onDone: (batch: BatchDetail) => void;
  onClose: () => void;
}) {
  const [f, setF] = useState(
    editing
      ? {
          product_id: String(editing.product.id), official_batch_no: editing.official_batch_no,
          manufacturing_site: editing.manufacturing_site, manufacturing_date: editing.manufacturing_date ?? "",
          expiry_date: editing.expiry_date ?? "", batch_size: editing.batch_size, notes: editing.notes,
        }
      : BLANK,
  );
  const [products, setProducts] = useState<ProductMasterRow[]>([]);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof BLANK, value: string) => setF((p) => ({ ...p, [key]: value }));

  useEffect(() => {
    if (editing) return;
    apiGet<Page<ProductMasterRow>>("/api/product-master/?active=1&page_size=200")
      .then((page) => setProducts(page.results))
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load the products."));
  }, [editing]);

  const save = async () => {
    setBusy(true);
    setError("");
    const body = {
      official_batch_no: f.official_batch_no,
      manufacturing_site: f.manufacturing_site,
      manufacturing_date: f.manufacturing_date || null,
      expiry_date: f.expiry_date || null,
      batch_size: f.batch_size,
      notes: f.notes,
    };
    try {
      onDone(
        editing
          ? await apiPatch<BatchDetail>(`/api/batches/${editing.id}/`, { ...body, reason })
          : await apiPost<BatchDetail>("/api/batches/", { ...body, product_id: Number(f.product_id) }),
      );
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the batch.");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal wide" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3>{editing ? `Correct ${editing.internal_id}` : "New batch"}</h3>
        <p className="modal-sub">
          The official batch number is stored exactly as the manufacturer assigned it. The system
          issues its own internal ID alongside it.
        </p>
        {!editing && (
          <Field label="Product" required>
            <select value={f.product_id} onChange={(e) => set("product_id", e.target.value)}>
              <option value="">— choose product —</option>
              {products.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.code})</option>)}
            </select>
          </Field>
        )}
        <div className="form-row">
          <Field label="Official batch number" required>
            <input value={f.official_batch_no} onChange={(e) => set("official_batch_no", e.target.value)} autoFocus />
          </Field>
          <Field label="Manufacturing site">
            <input value={f.manufacturing_site} onChange={(e) => set("manufacturing_site", e.target.value)}
              placeholder="If applicable" />
          </Field>
        </div>
        <div className="form-row">
          <Field label="Date of manufacture">
            <input type="date" value={f.manufacturing_date} onChange={(e) => set("manufacturing_date", e.target.value)} />
          </Field>
          <Field label="Expiry / retest date">
            <input type="date" value={f.expiry_date} onChange={(e) => set("expiry_date", e.target.value)} />
          </Field>
        </div>
        <div className="form-row">
          <Field label="Batch size">
            <input value={f.batch_size} onChange={(e) => set("batch_size", e.target.value)} placeholder="e.g. 100,000 tablets" />
          </Field>
          <Field label="Notes">
            <input value={f.notes} onChange={(e) => set("notes", e.target.value)} />
          </Field>
        </div>
        {editing && (
          <Field label="Why is it being corrected?" required hint="Kept on the record with the old values.">
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        )}
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="subtle" disabled={busy} onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || !f.official_batch_no.trim() || !f.product_id || (!!editing && !reason.trim())}
            onClick={() => void save()}>
            {busy ? "Saving…" : editing ? "Save correction" : "Create batch"}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}
