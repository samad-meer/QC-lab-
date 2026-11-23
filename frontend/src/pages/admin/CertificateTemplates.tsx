import { useState } from "react";
import { apiDelete, apiPatch, apiPost } from "../../api";
import ConfirmModal from "../../components/ConfirmModal";
import { Message } from "../../components/Feedback";
import Field from "../../components/Field";
import ListCard from "../../components/list/ListCard";
import { useToast } from "../../components/Toast";
import type { CertificateTemplateRow } from "../../types";
import { useList } from "../../useList";
import ModalBackdrop from "../../components/ModalBackdrop";

const OPTIONS: { key: keyof CertificateTemplateRow; label: string }[] = [
  { key: "show_method", label: "Method column" },
  { key: "show_internal_batch_id", label: "Internal batch ID" },
  { key: "show_manufacturing_site", label: "Manufacturing site" },
  { key: "show_dosage_form", label: "Dosage form and strength" },
  { key: "show_analysis_dates", label: "Analysis dates" },
  { key: "show_storage_condition", label: "Storage condition" },
];

const BLANK = {
  name: "", title: "Certificate of Analysis", header_note: "", footer_note: "", show_method: true,
  show_internal_batch_id: true, show_manufacturing_site: true, show_dosage_form: true, show_analysis_dates: true,
  show_storage_condition: true,
};

function TemplateModal({
  editing,
  onDone,
  onClose,
}: {
  editing: CertificateTemplateRow | null;
  onDone: () => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const [f, setF] = useState(editing ?? BLANK);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setError("");
    const { name, title, header_note, footer_note } = f;
    const body = { name, title, header_note, footer_note, ...Object.fromEntries(OPTIONS.map((o) => [o.key, f[o.key as keyof typeof f]])) };
    try {
      await (editing
        ? apiPatch(`/api/certificate-templates/${editing.id}/`, body)
        : apiPost("/api/certificate-templates/", body));
      toast("ok", "Template saved", "Certificates already signed keep the layout they were signed with.");
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the template.");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal wide" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3>{editing ? `Edit ${editing.name}` : "New certificate template"}</h3>
        <p className="modal-sub">
          A template sets how a certificate looks. Tests, limits, results, outcomes and signatures always
          print, and no template can remove them.
        </p>
        <Field label="Template name" required>
          <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoFocus />
        </Field>
        <Field label="Title on the certificate" required>
          <input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        </Field>
        <Field label="Line under the title">
          <input value={f.header_note} onChange={(e) => setF({ ...f, header_note: e.target.value })} placeholder="e.g. For export" />
        </Field>
        <Field label="Footer" hint="Blank uses the footer in Settings">
          <textarea rows={2} value={f.footer_note} onChange={(e) => setF({ ...f, footer_note: e.target.value })} />
        </Field>
        <div className="option-grid">
          {OPTIONS.map((o) => (
            <label className="cl-flag" key={o.key}>
              <input type="checkbox" checked={Boolean(f[o.key as keyof typeof f])}
                onChange={(e) => setF({ ...f, [o.key]: e.target.checked })} />
              {o.label}
            </label>
          ))}
        </div>
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="subtle" disabled={busy} onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || !f.name.trim() || !f.title.trim()} onClick={() => void save()}>
            {busy ? "Saving…" : "Save template"}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}

/** How certificates are laid out. Each product uses the default unless it names another. */
export default function CertificateTemplates() {
  const toast = useToast();
  const list = useList<CertificateTemplateRow, { can_manage: boolean }>("/api/certificate-templates/");
  const [editing, setEditing] = useState<CertificateTemplateRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<CertificateTemplateRow | null>(null);
  const canManage = list.data?.can_manage ?? false;

  const act = async (action: () => Promise<unknown>, ok: string) => {
    try {
      await action();
      toast("ok", ok);
      await list.reload();
    } catch (err) {
      toast("error", "Not done", err instanceof Error ? err.message : undefined);
    }
  };

  return (
    <>
      <div className="page-head">
        <h1>Certificate templates</h1>
        <p className="sub">
          The title, footer and optional details of a certificate. The layout is frozen when the analyst
          signs, so changing a template never alters a signed certificate. Choose a product's template on
          the Products screen.
        </p>
      </div>

      <ListCard
        title="Templates"
        list={list}
        failure="Could not load the templates"
        actions={canManage && <button className="primary small" onClick={() => setCreating(true)}>+ New template</button>}
      >
        {(rows) => (
          <div className="table-wrap">
            <table className="grid">
              <thead><tr><th>Template</th><th>Title</th><th>Leaves out</th><th>Products</th><th /></tr></thead>
              <tbody>
                {rows.map((t) => {
                  const off = OPTIONS.filter((o) => !t[o.key]).map((o) => o.label);
                  return (
                    <tr key={t.id}>
                      <td className="cell-title">
                        {t.name}
                        {t.is_default && <span className="badge info" style={{ marginLeft: 7 }}>default</span>}
                      </td>
                      <td>{t.title}</td>
                      <td>{off.length ? off.join(", ") : "Nothing"}</td>
                      <td className="num" title={t.is_default ? "Includes every product without a template of its own" : undefined}>
                        {t.product_count}
                      </td>
                      <td>
                        {canManage && (
                          <div className="actions-bar">
                            <button className="subtle small" onClick={() => setEditing(t)}>Edit</button>
                            {!t.is_default && (
                              <>
                                <button className="subtle small"
                                  onClick={() => void act(() => apiPatch(`/api/certificate-templates/${t.id}/`, { is_default: true }), `${t.name} is now the default`)}>
                                  Make default
                                </button>
                                <button className="danger small" disabled={t.product_count > 0}
                                  title={t.product_count > 0 ? "Products use this template. Move them to another one first." : undefined}
                                  onClick={() => setDeleting(t)}>
                                  Delete
                                </button>
                              </>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </ListCard>
      <Message kind="info">A template cannot remove a test, limit, result, outcome or signature from a certificate.</Message>

      {(creating || editing) && (
        <TemplateModal
          editing={editing}
          onDone={() => void list.reload()}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
        />
      )}
      {deleting && (
        <ConfirmModal
          title={`Delete “${deleting.name}”?`}
          confirmText="Delete template"
          onConfirm={async () => {
            await apiDelete(`/api/certificate-templates/${deleting.id}/`);
            toast("ok", `${deleting.name} deleted`);
            setDeleting(null);
            await list.reload();
          }}
          onClose={() => setDeleting(null)}
        >
          This cannot be undone. Certificates already signed keep their layout, and the deletion is recorded
          in the activity log.
        </ConfirmModal>
      )}
    </>
  );
}
