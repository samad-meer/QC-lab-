import { useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost } from "../../api";
import { useAuth } from "../../auth";
import Avatar from "../../components/Avatar";
import { Message } from "../../components/Feedback";
import ListCard from "../../components/list/ListCard";
import { useToast } from "../../components/Toast";
import type { AdminUser, Role, Section } from "../../types";
import { useList } from "../../useList";
import { fmtDateTime, todayInput } from "../../util";
import ModalBackdrop from "../../components/ModalBackdrop";

interface FormState {
  first_name: string;
  last_name: string;
  username: string;
  email: string;
  password: string;
  role_id: string;
  section_ids: number[];
  employee_id: string;
  designation: string;
  joining_date: string;
  phone: string;
}

/** Row actions as icons, drawn like the rest of the app's. Each button names itself for a screen reader. */
const ICONS = {
  edit: "M4 20l4-1 11-11-3-3L5 16z M14 6l3 3",
  password: "M15 7a4 4 0 1 1-3.5 6L5 19.5V22H2v-3l6.5-6.5A4 4 0 0 1 15 7z M16 8h.01",
  deactivate: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M2 21c1.3-3.6 3.9-5.5 7-5.5 1.6 0 3 .4 4.2 1.3 M16 15l5 5 M21 15l-5 5",
  reactivate: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M2 21c1.3-3.6 3.9-5.5 7-5.5 1.6 0 3 .4 4.2 1.3 M15 18l2 2 4-4",
};

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const BLANK: FormState = {
  first_name: "", last_name: "", username: "", email: "",
  password: "", role_id: "", section_ids: [],
  // A new starter usually joins today, so the date begins filled in.
  employee_id: "", designation: "", joining_date: todayInput(), phone: "",
};

function UserModal({
  editing,
  roles,
  sections,
  onDone,
  onClose,
}: {
  editing: AdminUser | null;
  roles: Role[];
  sections: Section[];
  onDone: () => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const [f, setF] = useState<FormState>(
    editing
      ? {
          first_name: editing.first_name, last_name: editing.last_name,
          username: editing.username, email: editing.email, password: "",
          role_id: String(editing.role?.id ?? ""), section_ids: editing.section_ids,
          employee_id: editing.employee_id ?? "", designation: editing.designation ?? "",
          joining_date: editing.joining_date ?? "", phone: editing.phone ?? "",
        }
      : { ...BLANK },
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: keyof FormState, v: unknown) => setF((p) => ({ ...p, [k]: v }));

  const toggleSection = (id: number) =>
    set(
      "section_ids",
      f.section_ids.includes(id) ? f.section_ids.filter((s) => s !== id) : [...f.section_ids, id],
    );

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const employment = {
        employee_id: f.employee_id, designation: f.designation,
        joining_date: f.joining_date || null, phone: f.phone,
      };
      if (editing) {
        await apiPatch(`/api/auth/users/${editing.id}/`, {
          first_name: f.first_name, last_name: f.last_name, email: f.email,
          role_id: Number(f.role_id), section_ids: f.section_ids, ...employment,
        });
        toast("ok", `${f.first_name} ${f.last_name} updated`.trim());
      } else {
        await apiPost("/api/auth/users/", {
          ...f, ...employment, role_id: Number(f.role_id),
        });
        toast("ok", `${f.username} created`, "They can sign in now.");
      }
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
      setBusy(false);
    }
  };

  const selectedRole = roles.find((r) => String(r.id) === f.role_id);
  const needsSections = selectedRole?.permissions.includes("result.enter");

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div
        className="modal wide"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <h3>{editing ? `Edit ${editing.name}` : "New user"}</h3>
        <div className="form-row">
          <label className="field">
            First name
            <input value={f.first_name} onChange={(e) => set("first_name", e.target.value)} autoFocus />
          </label>
          <label className="field">
            Last name
            <input value={f.last_name} onChange={(e) => set("last_name", e.target.value)} />
          </label>
        </div>
        <div className="form-row">
          <label className="field">
            Username
            <input
              value={f.username}
              onChange={(e) => set("username", e.target.value)}
              disabled={!!editing}
            />
          </label>
          <label className="field">
            Email
            <input type="email" value={f.email} onChange={(e) => set("email", e.target.value)} />
          </label>
        </div>
        {!editing && (
          <label className="field">
            Password
            <span className="note">Temporary: they choose their own the first time they sign in.</span>
            <input
              type="password"
              value={f.password}
              onChange={(e) => set("password", e.target.value)}
              autoComplete="new-password"
            />
          </label>
        )}
        <div className="form-row">
          <label className="field">
            Employee ID
            <input
              value={f.employee_id}
              onChange={(e) => set("employee_id", e.target.value)}
              placeholder="e.g. EMP-0142"
            />
          </label>
          <label className="field">
            Designation
            <input
              value={f.designation}
              onChange={(e) => set("designation", e.target.value)}
              placeholder="e.g. Senior Analyst"
            />
          </label>
        </div>
        <div className="form-row">
          <label className="field">
            Date of joining
            <input
              type="date"
              value={f.joining_date}
              onChange={(e) => set("joining_date", e.target.value)}
            />
          </label>
          <label className="field">
            Phone
            <input value={f.phone} onChange={(e) => set("phone", e.target.value)} />
          </label>
        </div>
        <label className="field">
          Role
          <select value={f.role_id} onChange={(e) => set("role_id", e.target.value)}>
            <option value="">— choose role —</option>
            {roles.filter((r) => r.is_active).map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </label>
        {selectedRole && (
          <div style={{ fontSize: 12.5, color: "var(--ink-3)", marginTop: -8 }}>
            {selectedRole.permissions.length} permission
            {selectedRole.permissions.length === 1 ? "" : "s"}: {selectedRole.description}
          </div>
        )}
        {needsSections && (
          <div className="field">
            <span>
              Trained for sections{" "}
              <span className="note">Only these sections may assign work to them.</span>
            </span>
            <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
              {sections.map((s) => (
                <label key={s.id} style={{ display: "flex", gap: 9, alignItems: "center", fontWeight: 500 }}>
                  <input
                    type="checkbox"
                    checked={f.section_ids.includes(s.id)}
                    onChange={() => toggleSection(s.id)}
                    style={{ width: 16, height: 16 }}
                  />
                  {s.name}
                </label>
              ))}
            </div>
          </div>
        )}
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button
            className="primary"
            onClick={() => void save()}
            disabled={busy || !f.role_id || (!editing && (!f.username || !f.password))}
          >
            {busy ? "Saving…" : editing ? "Save changes" : "Create user"}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}

function ResetPasswordModal({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const toast = useToast();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await apiPost(`/api/auth/users/${user.id}/reset-password/`, { password });
      toast("ok", `Password reset for ${user.name}`, "Tell them to change it after signing in.");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset.");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3>Reset password — {user.name}</h3>
        <p className="modal-sub">
          The reset is recorded in the audit trail; the password itself never is.
        </p>
        <label className="field">
          New password
          <input
            type="password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
        </label>
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="primary" onClick={() => void save()} disabled={busy || !password}>
            {busy ? "Resetting…" : "Reset password"}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}

export default function Users() {
  const toast = useToast();
  const { user: me } = useAuth();
  const users = useList<AdminUser, { active: number }>("/api/auth/users/");
  const [roles, setRoles] = useState<Role[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<AdminUser | null>(null);

  useEffect(() => {
    Promise.all([apiGet<Role[]>("/api/auth/role-options/"), apiGet<Section[]>("/api/sections/")])
      .then(([r, s]) => {
        setRoles(r);
        setSections(s);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load roles and sections."));
  }, []);

  const setActive = async (u: AdminUser, active: boolean) => {
    try {
      await apiPatch(`/api/auth/users/${u.id}/`, { is_active: active });
      toast("ok", `${u.name} ${active ? "reactivated" : "deactivated"}`);
      await users.reload();
    } catch (err) {
      toast("error", "Could not change the account", err instanceof Error ? err.message : "");
    }
  };

  return (
    <>
      <div className="page-head">
        <h1>Users</h1>
        <p className="sub">
          Create people and give them a role. Accounts are never deleted — their names appear on
          signed certificates — so leavers are deactivated instead.
        </p>
      </div>

      {error && <div style={{ marginBottom: 16 }}><Message kind="error">{error}</Message></div>}

      <ListCard
        title="All users"
        exportable
        hint={users.data ? `${users.data.active} active` : undefined}
        list={users}
        failure="Could not load users"
        emptyTitle="No users yet"
        actions={<button className="primary small" onClick={() => setCreating(true)}>+ New user</button>}
      >
        {(rows) => (
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Name</th><th>Employee ID</th><th>Username</th><th>Role</th>
                    <th>Sections</th><th>Last sign-in</th><th /></tr>
                </thead>
                <tbody>
                  {rows.map((u) => (
                    <tr key={u.id} style={{ opacity: u.is_active ? 1 : 0.55 }}>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <Avatar name={u.name} photoUrl={u.photo_url} size={30} />
                          <div>
                            <div className="cell-title">
                              {u.name}
                              {u.id === me?.id && <span className="badge info" style={{ marginLeft: 7 }}>you</span>}
                              {!u.is_active && <span className="badge muted" style={{ marginLeft: 7 }}>inactive</span>}
                            </div>
                            <div className="cell-sub">{u.designation || u.email || "—"}</div>
                          </div>
                        </div>
                      </td>
                      <td className="mono">{u.employee_id || "—"}</td>
                      <td className="mono">{u.username}</td>
                      <td>
                        {u.role ? u.role.name : <span className="badge fail">No role</span>}
                        <div className="cell-sub">{u.permissions.length} permissions</div>
                      </td>
                      <td>{u.sections.length ? u.sections.join(", ") : "—"}</td>
                      <td>{u.last_login ? fmtDateTime(u.last_login) : "never"}</td>
                      <td>
                        <div className="actions-bar row-icons">
                          <button
                            className="icon-btn small"
                            onClick={() => setEditing(u)}
                            title="Edit"
                            aria-label={`Edit ${u.name}`}
                          >
                            <Icon d={ICONS.edit} />
                          </button>
                          <button
                            className="icon-btn small"
                            onClick={() => setResetting(u)}
                            title="Reset password"
                            aria-label={`Reset the password of ${u.name}`}
                          >
                            <Icon d={ICONS.password} />
                          </button>
                          {u.id !== me?.id && (
                            <button
                              className={`icon-btn small ${u.is_active ? "danger" : "ok"}`}
                              onClick={() => void setActive(u, !u.is_active)}
                              title={u.is_active ? "Deactivate" : "Reactivate"}
                              aria-label={`${u.is_active ? "Deactivate" : "Reactivate"} ${u.name}`}
                            >
                              <Icon d={u.is_active ? ICONS.deactivate : ICONS.reactivate} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
        )}
      </ListCard>

      {(creating || editing) && (
        <UserModal
          editing={editing}
          roles={roles}
          sections={sections}
          onDone={() => void users.reload()}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
        />
      )}
      {resetting && <ResetPasswordModal user={resetting} onClose={() => setResetting(null)} />}
    </>
  );
}
