import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiDelete, apiGet, apiPost, apiPut, apiPatch } from "../../api";
import ConfirmModal from "../../components/ConfirmModal";
import { Message, TableSkeleton } from "../../components/Feedback";
import { useToast } from "../../components/Toast";
import type {
  ConflictPair,
  GrantHistoryRow,
  Permission,
  PermissionDef,
  PermissionModule,
  Role,
} from "../../types";
import { fmtDateTime } from "../../util";
import ModalBackdrop from "../../components/ModalBackdrop";

function NewRoleModal({ onDone, onClose }: { onDone: () => void; onClose: () => void }) {
  const toast = useToast();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await apiPost("/api/auth/roles/", { code, name, description });
      toast("ok", `Role “${name}” created`, "Now give it permissions.");
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the role.");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3>New role</h3>
        <p className="modal-sub">
          A role starts with no permissions. Give it what it needs on the next screen.
        </p>
        <label className="field">
          Name
          <input
            autoFocus
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (!code || code === name.toUpperCase().replace(/[^A-Z0-9]+/g, "_")) {
                setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]+/g, "_"));
              }
            }}
            placeholder="e.g. Senior Analyst"
          />
        </label>
        <label className="field">
          Code <span className="note">Used internally; cannot be changed later.</span>
          <input
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_"))}
          />
        </label>
        <label className="field">
          Description
          <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="primary" onClick={() => void save()} disabled={busy || !code || !name}>
            {busy ? "Creating…" : "Create role"}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}

function RenameRoleModal({ role, onDone, onClose }: { role: Role; onDone: () => void; onClose: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(role.name);
  const [description, setDescription] = useState(role.description);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await apiPatch(`/api/auth/roles/${role.id}/`, { name, description });
      toast("ok", `Role “${name}” saved`);
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the role.");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Rename {role.name}</h3>
        <p className="modal-sub">The code {role.code} stays the same. People in this role keep it.</p>
        <label className="field">
          Name
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          Description
          <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="primary" onClick={() => void save()} disabled={busy || !name.trim()}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}

function HistoryModal({ role, onClose }: { role: Role; onClose: () => void }) {
  const [rows, setRows] = useState<GrantHistoryRow[] | null>(null);

  useEffect(() => {
    apiGet<GrantHistoryRow[]>(`/api/auth/roles/${role.id}/history/`).then(setRows).catch(() => setRows([]));
  }, [role.id]);

  return (
    <ModalBackdrop onClick={onClose}>
      <div
        className="modal wide"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <h3>Permission history — {role.name}</h3>
        <p className="modal-sub">
          Every grant and revoke this role has ever had. Nothing is removed, so “who could do
          what, and when” is always answerable.
        </p>
        {rows === null ? (
          <TableSkeleton rows={3} cols={4} />
        ) : rows.length === 0 ? (
          <div className="empty"><div className="empty-title">No changes recorded yet</div></div>
        ) : (
          <div className="table-wrap" style={{ maxHeight: 380, overflowY: "auto" }}>
            <table className="grid">
              <thead>
                <tr><th>Permission</th><th>Granted</th><th>Revoked</th><th>Reason</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={r.revoked_at ? "superseded" : ""}>
                    <td className="cell-title">{r.label}</td>
                    <td>
                      {fmtDateTime(r.granted_at)}
                      <div className="cell-sub">{r.granted_by_name}</div>
                    </td>
                    <td>
                      {r.revoked_at ? (
                        <>
                          {fmtDateTime(r.revoked_at)}
                          <div className="cell-sub">{r.revoked_by_name}</div>
                        </>
                      ) : (
                        <span className="badge pass">Active</span>
                      )}
                    </td>
                    <td>{r.reason || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="actions">
          <button className="ghost" onClick={onClose}>Close</button>
        </div>
      </div>
    </ModalBackdrop>
  );
}

const MODULE_TITLE: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--ink-3)",
  marginBottom: 9,
};

/**
 * One module's permissions. A permission that comes with another (seeing the
 * instruments, with managing them) shows ticked and fixed while that one is; a
 * long list (one per report) is grouped, compact, with tick all and clear all.
 */
function ModulePermissions({ module: mod, draft, held, labels, hiddenFeatures, onToggle, onSet }: {
  module: PermissionModule;
  draft: Set<string>;
  held: Permission[];
  labels: Map<string, string>;
  /** Switched off for everyone in Settings: granting it does nothing until it is shown again. */
  hiddenFeatures: Set<string>;
  onToggle: (key: string) => void;
  onSet: (keys: string[], on: boolean) => void;
}) {
  const plain = mod.permissions.filter((p) => !p.group);
  const grouped = mod.permissions.filter((p) => p.group);
  const groups = [...new Set(grouped.map((p) => p.group as string))];
  const keys = grouped.map((p) => p.key as string);
  const ticked = keys.filter((k) => draft.has(k)).length;
  const need = grouped[0]?.needs;
  const shut = Boolean(need) && !draft.has(need as string);

  const row = (p: PermissionDef, compact: boolean) => {
    const on = draft.has(p.key);
    const changed = on !== held.includes(p.key);
    const comesWith = p.included_with?.find((k) => draft.has(k));
    const why = comesWith
      ? `Comes with “${labels.get(comesWith)}”: whoever works on a register sees it.`
      : !compact && p.needs && on && !draft.has(p.needs)
        ? `Does nothing without “${labels.get(p.needs)}”.`
        : "";
    return (
      <label key={p.key}
        className={`perm-row${compact ? " compact" : ""}${on || comesWith ? " on" : ""}${changed ? " changed" : ""}`}>
        <input type="checkbox" checked={on || Boolean(comesWith)} disabled={Boolean(comesWith)}
          onChange={() => onToggle(p.key)} />
        <span>
          <span className="perm-label">
            {p.label}
            {changed && <span className="badge info">changed</span>}
            {hiddenFeatures.has(p.key) && (
              <span className="badge muted" title="Switched off for everyone in Settings → Features shown">
                hidden in Settings
              </span>
            )}
          </span>
          <span className="perm-help">{p.help}</span>
          {why && <span className="perm-why">{why}</span>}
        </span>
      </label>
    );
  };

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={MODULE_TITLE}>{mod.name}</div>
      {mod.note && <p className="perm-note">{mod.note}</p>}
      <div style={{ display: "grid", gap: 8 }}>{plain.map((p) => row(p, false))}</div>
      {grouped.length > 0 && (
        <div className={`perm-groups${shut ? " shut" : ""}`} role="group" aria-label={`${mod.name}, one by one`}>
          <div className="perm-groups-head">
            <b>{mod.key === "reports" ? "Reports this role opens" : "One by one"}</b>
            <span className="hint">{ticked} of {keys.length} ticked</span>
            <span className="grow" />
            <button type="button" className="link-btn" onClick={() => onSet(keys, true)}
              disabled={ticked === keys.length}>Tick all</button>
            <button type="button" className="link-btn" onClick={() => onSet(keys, false)}
              disabled={ticked === 0}>Clear all</button>
          </div>
          {shut && (
            <p className="perm-note">None of these opens until “{labels.get(need as string)}” above is ticked too.</p>
          )}
          {groups.map((g) => (
            <div key={g} className="perm-group">
              <div className="perm-group-title">{g}</div>
              <div className="perm-grid">{grouped.filter((p) => p.group === g).map((p) => row(p, true))}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Roles() {
  const toast = useToast();
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [modules, setModules] = useState<PermissionModule[]>([]);
  const [conflictPairs, setConflictPairs] = useState<ConflictPair[]>([]);
  const [hiddenFeatures, setHiddenFeatures] = useState<Set<string>>(new Set());
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [r, cat] = await Promise.all([
        apiGet<Role[]>("/api/auth/roles/"),
        apiGet<{ modules: PermissionModule[]; conflict_pairs: ConflictPair[]; hidden?: string[] }>(
          "/api/auth/permissions/",
        ),
      ]);
      setRoles(r);
      setModules(cat.modules);
      setHiddenFeatures(new Set(cat.hidden ?? []));
      setConflictPairs(cat.conflict_pairs);
      setSelectedId((prev) => prev ?? r[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load roles.");
      setRoles([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = roles?.find((r) => r.id === selectedId) ?? null;

  // Reset the draft whenever a different role is opened.
  useEffect(() => {
    if (selected) {
      setDraft(new Set(selected.permissions));
      setReason("");
      setError("");
    }
  }, [selected?.id, selected?.permissions.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  if (roles === null) {
    return (
      <div className="card"><div className="card-body flush"><TableSkeleton /></div></div>
    );
  }

  const dirty =
    selected &&
    (draft.size !== selected.permissions.length ||
      selected.permissions.some((p) => !draft.has(p)));

  const toggle = (key: string) => {
    setDraft((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  /** Tick or clear several at once: every report of a role, say. */
  const setMany = (keys: string[], on: boolean) => {
    setDraft((prev) => {
      const next = new Set(prev);
      keys.forEach((k) => (on ? next.add(k) : next.delete(k)));
      return next;
    });
  };

  const labels = new Map(modules.flatMap((m) => m.permissions.map((p) => [p.key as string, p.label])));

  const save = async () => {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      await apiPut<Role>(`/api/auth/roles/${selected.id}/permissions/`, {
        permissions: [...draft],
        reason,
      });
      toast("ok", `${selected.name} updated`, "The change is recorded in the permission history.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async () => {
    if (!selected) return;
    try {
      await apiPatch(`/api/auth/roles/${selected.id}/`, { is_active: !selected.is_active });
      toast("ok", `${selected.name} ${selected.is_active ? "deactivated" : "reactivated"}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the role.");
    }
  };

  // Warn live against the draft for permission pairs (they come from the
  // backend registry, so there is one definition of a conflict), plus the
  // conflicts the server derives from the review stages this role signs.
  const pairConflicts = conflictPairs.filter((c) => draft.has(c.a) && draft.has(c.b));
  const stageConflicts = (selected?.conflicts ?? []).filter((c) => c.b.startsWith("stage:"));
  const conflicts = [...new Set([...pairConflicts, ...stageConflicts].map((c) => c.message))];

  return (
    <>
      <div className="page-head">
        <h1>Roles and permissions</h1>
        <p className="sub">
          Roles are yours to define. What a role may do is set here and takes effect immediately —
          every change is recorded, and old grants are kept so you can always show who could do
          what at any date.
        </p>
      </div>

      <div className="side-by-side">
        <div className="card" style={{ margin: 0 }}>
          <div className="card-head">
            <h2>Roles</h2>
            <div className="spacer" />
            <button className="ghost small" onClick={() => setShowNew(true)}>+ New</button>
          </div>
          <div className="card-body flush">
            {roles.map((r) => (
              <button
                key={r.id}
                onClick={() => setSelectedId(r.id)}
                style={{
                  display: "block", width: "100%", textAlign: "left", font: "inherit",
                  padding: "12px 16px", border: "none", cursor: "pointer",
                  borderBottom: "1px solid var(--line)",
                  background: r.id === selectedId ? "var(--brand-soft)" : "transparent",
                  color: r.id === selectedId ? "var(--brand-soft-ink)" : "var(--ink)",
                }}
              >
                <div style={{ fontWeight: 650, display: "flex", alignItems: "center", gap: 7 }}>
                  {r.name}
                  {!r.is_active && <span className="badge muted">Inactive</span>}
                </div>
                <div className="cell-sub">
                  {r.permissions.length} permission{r.permissions.length === 1 ? "" : "s"} ·{" "}
                  {r.user_count} user{r.user_count === 1 ? "" : "s"}
                  {r.is_system && " · built in"}
                </div>
              </button>
            ))}
          </div>
        </div>

        {selected && (
          <div className="card" style={{ margin: 0 }}>
            <div className="card-head">
              <h2>{selected.name}</h2>
              <span className="hint">{selected.code}</span>
              <div className="spacer" />
              <button className="subtle small" onClick={() => setShowHistory(true)}>History</button>
              <button className="subtle small" onClick={() => setRenaming(true)}>Rename</button>
              {!selected.is_system && (
                <>
                  <button className="subtle small" onClick={() => void toggleActive()}>
                    {selected.is_active ? "Deactivate" : "Reactivate"}
                  </button>
                  <button className="danger small" onClick={() => setDeleting(true)}>Delete…</button>
                </>
              )}
            </div>
            <div className="card-body">
              {selected.description && (
                <p style={{ marginTop: 0, color: "var(--ink-2)", fontSize: 13.5 }}>
                  {selected.description}
                </p>
              )}

              {conflicts.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <Message kind="warn">
                    <b>Segregation of duties:</b> this role combines duties that are normally kept
                    apart. It is allowed — a small lab may need it — but it is recorded. The rule
                    that every signature on one certificate comes from a different person still
                    applies, unless the role holds “Act in anyone's place”.
                    <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                      {conflicts.map((m) => <li key={m}>{m}</li>)}
                    </ul>
                  </Message>
                </div>
              )}

              <div style={{ marginBottom: 20 }}>
                <div
                  style={{
                    fontSize: 11, fontWeight: 700, textTransform: "uppercase",
                    letterSpacing: "0.6px", color: "var(--ink-3)", marginBottom: 9,
                  }}
                >
                  Review signatures
                </div>
                <div style={{ fontSize: 13.5, color: "var(--ink-2)" }}>
                  {selected.review_stages.length === 0 ? (
                    <>This role signs no review stage.</>
                  ) : (
                    <ul style={{ margin: "0 0 6px", paddingLeft: 18, display: "grid", gap: 4 }}>
                      {selected.review_stages.map((s) => (
                        <li key={`${s.workflow}-${s.stage}`}>
                          Signs “{s.title}” in <b>{s.workflow}</b>
                        </li>
                      ))}
                    </ul>
                  )}{" "}
                  <span style={{ color: "var(--ink-3)" }}>
                    Who signs each stage is set on the{" "}
                    <Link to="/admin/workflows">Workflows</Link> screen, not here.
                  </span>
                </div>
              </div>

              {modules.map((mod) => (
                <ModulePermissions
                  key={mod.key}
                  module={mod}
                  draft={draft}
                  held={selected.permissions}
                  labels={labels}
                  hiddenFeatures={hiddenFeatures}
                  onToggle={toggle}
                  onSet={setMany}
                />
              ))}

              {error && <div style={{ marginBottom: 12 }}><Message kind="error">{error}</Message></div>}

              {dirty && (
                <div style={{ display: "grid", gap: 12 }}>
                  <label className="field">
                    Reason for this change <span className="note">Kept with the permission history.</span>
                    <input
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      placeholder="e.g. Approved under change request CR-2026-014"
                    />
                  </label>
                  <div className="actions-bar">
                    <button
                      className="ghost"
                      onClick={() => setDraft(new Set(selected.permissions))}
                      disabled={busy}
                    >
                      Discard changes
                    </button>
                    <div className="spacer" />
                    <button className="primary" onClick={() => void save()} disabled={busy}>
                      {busy ? "Saving…" : "Save permissions"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {showNew && <NewRoleModal onDone={() => void load()} onClose={() => setShowNew(false)} />}
      {renaming && selected && (
        <RenameRoleModal role={selected} onDone={() => void load()} onClose={() => setRenaming(false)} />
      )}
      {deleting && selected && (
        <ConfirmModal
          title={`Delete ${selected.name}?`}
          confirmText="Delete role"
          onConfirm={async () => {
            await apiDelete(`/api/auth/roles/${selected.id}/`);
            toast("ok", `${selected.name} deleted`);
            setDeleting(false);
            setSelectedId(null);
            await load();
          }}
          onClose={() => setDeleting(false)}
        >
          This cannot be undone. A role that people hold, or that has ever had a permission, stays on record:
          deactivate it instead.
        </ConfirmModal>
      )}
      {showHistory && selected && (
        <HistoryModal role={selected} onClose={() => setShowHistory(false)} />
      )}
    </>
  );
}
