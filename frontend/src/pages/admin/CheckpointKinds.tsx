import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch } from "../../api";
import { KindModal } from "../../components/CheckpointKindForm";
import { EmptyState, Message, TableSkeleton } from "../../components/Feedback";
import { useToast } from "../../components/Toast";
import type { CheckpointPreset } from "../../types";

function details(k: CheckpointPreset): string {
  if (k.kind === "CHOICE") {
    return k.choices.map((c) => (c.ok ? c.label : `${c.label} (flagged)`)).join(" / ");
  }
  const unit = k.kind === "PERCENT" ? "%" : k.unit;
  const limits = k.min_value !== null && k.max_value !== null ? `${k.min_value} – ${k.max_value}`
    : k.min_value !== null ? `NLT ${k.min_value}` : k.max_value !== null ? `NMT ${k.max_value}` : "";
  return [unit && `in ${unit}`, limits && `limit ${limits}${unit ? ` ${unit}` : ""}`,
    ["NUMBER", "PERCENT"].includes(k.kind) ? `${k.decimals} decimals` : ""].filter(Boolean).join(" · ") || "—";
}

/**
 * The lab's own kinds of value, offered in every stage beside the built-in ones:
 * Temperature in °C, Mixer speed in rpm, Equipment ID, Complies / Does not comply.
 */
export default function CheckpointKinds() {
  const toast = useToast();
  const [rows, setRows] = useState<CheckpointPreset[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<CheckpointPreset | "new" | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await apiGet<CheckpointPreset[]>("/api/checkpoint-kinds/?all=1"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the kinds.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (k: CheckpointPreset) => {
    try {
      await apiPatch(`/api/checkpoint-kinds/${k.id}/`, { is_active: !k.is_active });
      toast("ok", k.is_active ? `“${k.name}” retired` : `“${k.name}” offered again`,
        k.is_active ? "Stages that use it keep their copy." : undefined);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change it.");
    }
  };

  return (
    <>
      <div className="page-head">
        <h1>Check point kinds</h1>
        <p className="sub">
          The kinds of value a batch record can ask for, beyond the built-in ones: a measurement with its unit and limits,
          or a choice with its acceptable answers. Each is offered in every stage's “Kind of value” list. A stage keeps a
          copy when it is saved, so changing or retiring a kind here changes no stage already in use.
        </p>
      </div>
      {error && <Message kind="error">{error}</Message>}
      <div className="card">
        <div className="card-head">
          <h2>The lab's own kinds</h2>
          <span className="hint">{rows ? `${rows.filter((k) => k.is_active).length} offered` : ""}</span>
          <div className="spacer" />
          <button className="primary small" onClick={() => setEditing("new")}>+ New kind</button>
        </div>
        <div className="card-body flush">
          {!rows ? <TableSkeleton /> : rows.length === 0 ? (
            <EmptyState title="None yet"
              sub="Add one here, or from “+ New kind…” at the end of a check point's “Kind of value” list." />
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead><tr><th>Name</th><th>Based on</th><th>Unit, limits or options</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {rows.map((k) => (
                    <tr key={k.id}>
                      <td className="cell-title">{k.name}</td>
                      <td>{k.kind_label}</td>
                      <td>{details(k)}</td>
                      <td><span className={`badge ${k.is_active ? "pass" : "muted"}`}>{k.is_active ? "Offered" : "Retired"}</span></td>
                      <td>
                        <div className="actions-bar row-icons">
                          <button className="ghost small" onClick={() => setEditing(k)}>Edit</button>
                          <button className="subtle small" onClick={() => void toggle(k)}>{k.is_active ? "Retire" : "Offer again"}</button>
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
      {editing && (
        <KindModal
          editing={editing === "new" ? undefined : editing}
          onSaved={(k) => {
            toast("ok", editing === "new" ? `“${k.name}” added` : `“${k.name}” saved`);
            setEditing(null);
            void load();
          }}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  );
}
