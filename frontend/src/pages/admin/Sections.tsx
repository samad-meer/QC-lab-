import { useCallback, useEffect, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPost } from "../../api";
import ConfirmModal from "../../components/ConfirmModal";
import { EmptyState, Message, TableSkeleton } from "../../components/Feedback";
import Field from "../../components/Field";
import ModalBackdrop from "../../components/ModalBackdrop";
import { useToast } from "../../components/Toast";
import type { SectionRow } from "../../types";

function SectionModal({
  editing,
  onDone,
  onClose,
}: {
  editing: SectionRow | null;
  onDone: () => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const [code, setCode] = useState(editing?.code ?? "");
  const [name, setName] = useState(editing?.name ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await (editing
        ? apiPatch(`/api/section-master/${editing.id}/`, { name })
        : apiPost("/api/section-master/", { code, name }));
      toast("ok", editing ? "Section renamed" : `Section ${code} added`);
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the section.");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{editing ? `Rename ${editing.code}` : "New section"}</h3>
        {!editing && (
          <Field label="Code" required hint="Starts every sample number in this section, and can never be changed">
            <input
              value={code}
              maxLength={10}
              autoFocus
              placeholder="e.g. GF"
              onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
            />
          </Field>
        )}
        <Field label="Name" required>
          <input value={name} maxLength={100} autoFocus={!!editing} onChange={(e) => setName(e.target.value)} />
        </Field>
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="ghost" disabled={busy} onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || !name.trim() || !code} onClick={() => void save()}>
            {busy ? "Saving…" : editing ? "Save name" : "Add section"}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}

/** The lab's sections. A code is fixed once chosen; a section anything uses stays. */
export default function Sections() {
  const toast = useToast();
  const [rows, setRows] = useState<SectionRow[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<SectionRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<SectionRow | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await apiGet<SectionRow[]>("/api/section-master/"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the sections.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <Message kind="error">{error}</Message>;
  if (!rows) return <div className="card"><div className="card-body flush"><TableSkeleton /></div></div>;

  return (
    <>
      <div className="page-head">
        <h1>Sections</h1>
        <p className="sub">
          The parts of the lab that products, samples and people belong to. Each section's code starts its
          sample numbers, so a code is fixed once chosen. A section can be deleted only while nothing uses it.
        </p>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Sections</h2>
          <div className="spacer" />
          <button className="primary small" onClick={() => setCreating(true)}>+ New section</button>
        </div>
        <div className="card-body flush">
          {rows.length === 0 ? (
            <EmptyState title="No sections yet" sub="Add one to start registering products and samples." />
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead><tr><th>Code</th><th>Name</th><th>Products</th><th>Samples</th><th>People trained</th><th /></tr></thead>
                <tbody>
                  {rows.map((s) => {
                    const used = s.product_count + s.sample_count + s.user_count > 0;
                    return (
                      <tr key={s.id}>
                        <td className="cell-title">{s.code}</td>
                        <td>{s.name}</td>
                        <td className="num">{s.product_count}</td>
                        <td className="num">{s.sample_count}</td>
                        <td className="num">{s.user_count}</td>
                        <td>
                          <div className="actions-bar">
                            <button className="subtle small" onClick={() => setEditing(s)}>Rename</button>
                            <button className="danger small" disabled={used}
                              title={used ? "Products, samples or people use this section." : undefined}
                              onClick={() => setDeleting(s)}>
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {(creating || editing) && (
        <SectionModal
          editing={editing}
          onDone={() => void load()}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
        />
      )}
      {deleting && (
        <ConfirmModal
          title={`Delete section ${deleting.code}?`}
          confirmText="Delete section"
          onConfirm={async () => {
            await apiDelete(`/api/section-master/${deleting.id}/`);
            toast("ok", `Section ${deleting.code} deleted`);
            setDeleting(null);
            await load();
          }}
          onClose={() => setDeleting(null)}
        >
          This cannot be undone. The deletion is recorded in the activity log.
        </ConfirmModal>
      )}
    </>
  );
}
