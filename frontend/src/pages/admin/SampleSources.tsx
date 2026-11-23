import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost } from "../../api";
import { EmptyState, Message, TableSkeleton } from "../../components/Feedback";
import Field from "../../components/Field";
import ModalBackdrop from "../../components/ModalBackdrop";
import { useToast } from "../../components/Toast";
import type { SampleSource } from "../../types";

function SourceModal({
  editing,
  onDone,
  onClose,
}: {
  editing: SampleSource | null;
  onDone: () => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(editing?.name ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await (editing
        ? apiPatch(`/api/sample-source-master/${editing.id}/`, { name })
        : apiPost("/api/sample-source-master/", { name }));
      toast("ok", editing ? "Name changed" : `${name.trim()} added`);
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the name.");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{editing ? `Rename ${editing.name}` : "Add a name"}</h3>
        <Field
          label="Name"
          required
          hint={editing
            ? "Samples already received keep the name they were received under"
            : "A department, a supplier, or the person who brings samples"}
        >
          <input
            value={name}
            maxLength={200}
            autoFocus
            placeholder="e.g. Production, Ali Raza (Store)"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && name.trim() && !busy && void save()}
          />
        </Field>
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="ghost" disabled={busy} onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || !name.trim()} onClick={() => void save()}>
            {busy ? "Saving…" : editing ? "Save name" : "Add name"}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}

/** Who samples are received from. The front desk picks from this list instead of typing. */
export default function SampleSources() {
  const toast = useToast();
  const [rows, setRows] = useState<SampleSource[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<SampleSource | null>(null);
  const [creating, setCreating] = useState(false);
  const [switching, setSwitching] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await apiGet<SampleSource[]>("/api/sample-source-master/"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the list.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const setActive = async (s: SampleSource, active: boolean) => {
    setSwitching(s.id);
    try {
      await apiPatch(`/api/sample-source-master/${s.id}/`, { is_active: active });
      toast("ok", active ? `${s.name} is offered again` : `${s.name} is no longer offered`);
      await load();
    } catch (err) {
      toast("error", "Not changed", err instanceof Error ? err.message : undefined);
    } finally {
      setSwitching(null);
    }
  };

  if (error) return <Message kind="error">{error}</Message>;
  if (!rows) return <div className="card"><div className="card-body flush"><TableSkeleton /></div></div>;

  const active = rows.filter((s) => s.is_active).length;

  return (
    <>
      <div className="page-head">
        <h1>Received from</h1>
        <p className="sub">
          The names the front desk chooses from when a sample arrives, so one person or department is never
          typed three different ways. A name is never deleted: deactivate one that is no longer used.
        </p>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Names</h2>
          <span className="hint">{active} offered at the front desk</span>
          <div className="spacer" />
          <button className="primary small" onClick={() => setCreating(true)}>+ Add name</button>
        </div>
        <div className="card-body flush">
          {rows.length === 0 ? (
            <EmptyState title="No names yet" sub="Add one so the front desk can register samples." />
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead><tr><th>Name</th><th /></tr></thead>
                <tbody>
                  {rows.map((s) => (
                    <tr key={s.id} style={{ opacity: s.is_active ? 1 : 0.55 }}>
                      <td className="cell-title">
                        {s.name}
                        {!s.is_active && <span className="badge muted" style={{ marginLeft: 7 }}>inactive</span>}
                      </td>
                      <td>
                        <div className="actions-bar">
                          <button className="subtle small" onClick={() => setEditing(s)}>Rename</button>
                          <button className="subtle small" disabled={switching === s.id}
                            onClick={() => void setActive(s, !s.is_active)}>
                            {s.is_active ? "Deactivate" : "Reactivate"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {(creating || editing) && (
        <SourceModal
          editing={editing}
          onDone={() => void load()}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
        />
      )}
    </>
  );
}
