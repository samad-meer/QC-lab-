import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPatch } from "../api";
import { useAuth } from "../auth";
import Avatar from "../components/Avatar";
import { Message } from "../components/Feedback";
import PasswordForm from "../components/PasswordForm";
import { useToast } from "../components/Toast";
import type { Profile as ProfileType } from "../types";
import { fmtDate, fmtDateTime } from "../util";

function PhotoPanel({
  profile,
  onChanged,
}: {
  profile: ProfileType;
  onChanged: (p: ProfileType) => void;
}) {
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const upload = async (file: File) => {
    setBusy(true);
    setError("");
    try {
      // Multipart, so this cannot go through the JSON api helper.
      const body = new FormData();
      body.append("photo", file);
      const csrf = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/)?.[1] ?? "";
      const res = await fetch("/api/auth/profile/photo/", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": decodeURIComponent(csrf) },
        body,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail ?? "Upload failed.");
      onChanged(data as ProfileType);
      toast("ok", "Photo updated");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const remove = async () => {
    setBusy(true);
    setError("");
    try {
      const csrf = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/)?.[1] ?? "";
      const res = await fetch("/api/auth/profile/photo/", {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "X-CSRFToken": decodeURIComponent(csrf) },
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail ?? "Could not remove the photo.");
      onChanged(data as ProfileType);
      toast("ok", "Photo removed");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove the photo.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "grid", gap: 12, justifyItems: "center" }}>
      <Avatar name={profile.name} photoUrl={profile.photo_url} size={104} />
      <input
        ref={fileRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void upload(file);
        }}
      />
      <div className="actions-bar" style={{ justifyContent: "center" }}>
        <button className="ghost small" disabled={busy} onClick={() => fileRef.current?.click()}>
          {busy ? "Working…" : profile.photo_url ? "Replace" : "Add photo"}
        </button>
        {profile.photo_url && (
          <button className="danger small" disabled={busy} onClick={() => void remove()}>
            Remove
          </button>
        )}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--ink-3)", textAlign: "center", maxWidth: 190 }}>
        Optional. JPEG, PNG or WebP, up to 2&nbsp;MB. Shown in the app only — never on a
        certificate.
      </div>
      {error && <Message kind="error">{error}</Message>}
    </div>
  );
}

export default function Profile() {
  const toast = useToast();
  const { refreshUser } = useAuth();
  const [profile, setProfile] = useState<ProfileType | null>(null);
  const [loadError, setLoadError] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  const apply = useCallback(
    (p: ProfileType) => {
      setProfile(p);
      setPhone(p.phone ?? "");
      setEmail(p.email ?? "");
      // Keep the top bar in step — the avatar lives there too.
      void refreshUser();
    },
    [refreshUser],
  );

  useEffect(() => {
    apiGet<ProfileType>("/api/auth/profile/")
      .then(apply)
      .catch((err) =>
        setLoadError(err instanceof Error ? err.message : "Could not load your profile."),
      );
    // apply is stable per refreshUser; running once on mount is intended.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loadError) return <Message kind="error">{loadError}</Message>;
  if (!profile) {
    return (
      <div className="card">
        <div className="card-body">
          <div className="sk" style={{ width: 220, height: 14 }} />
        </div>
      </div>
    );
  }

  const contactDirty = phone !== (profile.phone ?? "") || email !== (profile.email ?? "");

  const saveContact = async () => {
    setSaving(true);
    setSaveError("");
    try {
      apply(await apiPatch<ProfileType>("/api/auth/profile/", { phone, email }));
      toast("ok", "Contact details saved");
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  };

  const adminSet = (value: string | null | undefined, formatted?: string) =>
    value ? (
      <div className="v">{formatted ?? value}</div>
    ) : (
      <div className="v" style={{ color: "var(--ink-3)", fontWeight: 400 }}>
        Not set
      </div>
    );

  return (
    <>
      <div className="page-head">
        <h1>My account</h1>
        <p className="sub">
          Your record and what you are permitted to do. Employment details and your role are
          maintained by an administrator. You can change your photo, contact details and
          password here.
        </p>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Identity</h2>
        </div>
        <div className="card-body side-by-side narrow">
          <PhotoPanel profile={profile} onChanged={apply} />

          <div style={{ display: "grid", gap: 20, alignContent: "start" }}>
            <div className="kv">
              <div>
                <div className="k">Name</div>
                <div className="v">{profile.name}</div>
              </div>
              <div>
                <div className="k">Username</div>
                <div className="v mono" style={{ fontSize: 13.5 }}>{profile.username}</div>
              </div>
              <div>
                <div className="k">Employee ID</div>
                {adminSet(profile.employee_id)}
              </div>
              <div>
                <div className="k">Designation</div>
                {adminSet(profile.designation)}
              </div>
              <div>
                <div className="k">Date of joining</div>
                {adminSet(profile.joining_date, profile.joining_date ? fmtDate(profile.joining_date) : undefined)}
              </div>
              <div>
                <div className="k">Account created</div>
                <div className="v">{fmtDate(profile.date_joined.slice(0, 10))}</div>
              </div>
            </div>
            <div style={{ fontSize: 12.5, color: "var(--ink-3)" }}>
              Name, employee ID, designation and date of joining are set by an administrator.
            </div>

            <div style={{ borderTop: "1px solid var(--line)", paddingTop: 18 }}>
              <div className="form-row" style={{ maxWidth: 520 }}>
                <label className="field">
                  Phone
                  <input value={phone} onChange={(e) => setPhone(e.target.value)} />
                </label>
                <label className="field">
                  Email
                  <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
                </label>
              </div>
              {saveError && (
                <div style={{ marginTop: 12 }}>
                  <Message kind="error">{saveError}</Message>
                </div>
              )}
              {contactDirty && (
                <div className="actions-bar" style={{ marginTop: 14 }}>
                  <button
                    className="ghost"
                    onClick={() => {
                      setPhone(profile.phone ?? "");
                      setEmail(profile.email ?? "");
                      setSaveError("");
                    }}
                    disabled={saving}
                  >
                    Discard
                  </button>
                  <button className="primary" onClick={() => void saveContact()} disabled={saving}>
                    {saving ? "Saving…" : "Save contact details"}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Access</h2>
          <span className="hint">What you are permitted to do</span>
        </div>
        <div className="card-body">
          <div className="kv" style={{ marginBottom: 18 }}>
            <div>
              <div className="k">Role</div>
              <div className="v">{profile.role?.name ?? "No role"}</div>
            </div>
            <div style={{ gridColumn: "span 3" }}>
              <div className="k">What this role is for</div>
              <div className="v" style={{ fontWeight: 400 }}>
                {profile.role_description || "—"}
              </div>
            </div>
          </div>

          <div className="k" style={{ marginBottom: 7 }}>Trained for sections</div>
          <div style={{ marginBottom: 20 }}>
            {profile.section_names.length === 0 ? (
              <span style={{ color: "var(--ink-3)", fontSize: 13.5 }}>
                None recorded — you cannot be assigned samples until an administrator adds one.
              </span>
            ) : (
              <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
                {profile.section_names.map((s) => (
                  <span key={s} className="badge info">{s}</span>
                ))}
              </div>
            )}
          </div>

          {profile.review_stages.length > 0 && (
            <>
              <div className="k" style={{ marginBottom: 7 }}>Review signatures</div>
              <ul style={{ margin: "0 0 20px", paddingLeft: 20, display: "grid", gap: 5, fontSize: 13.5 }}>
                {profile.review_stages.map((s) => (
                  <li key={`${s.workflow}-${s.stage}`}>
                    You sign “{s.title}” in {s.workflow}
                  </li>
                ))}
              </ul>
            </>
          )}

          <div className="k" style={{ marginBottom: 7 }}>What you can do</div>
          {profile.permission_groups.length === 0 ? (
            <span style={{ color: "var(--ink-3)", fontSize: 13.5 }}>Nothing yet. Ask an administrator.</span>
          ) : (
            <>
              <p className="cell-sub" style={{ margin: "0 0 10px" }}>
                From your role{profile.role ? <>, <b>{profile.role.name}</b></> : null}. Point at any of them for
                what it lets you do. An administrator changes them on the Roles screen.
              </p>
              <div className="cap-grid">
                {profile.permission_groups.map((g) => {
                  const plain = g.permissions.filter((p) => !p.group);
                  const listed = g.permissions.filter((p) => p.group);
                  return (
                    <section key={g.key} className="cap-group" aria-label={g.name}>
                      <div className="cap-head">
                        <b>{g.name}</b>
                        <span className="cap-count">{g.permissions.length}</span>
                      </div>
                      {plain.length > 0 && (
                        <ul className="cap-list">
                          {plain.map((p) => (
                            <li key={p.key} title={p.help} className={p.key === "admin.override" ? "attention" : undefined}>
                              {p.label}
                              {p.key === "admin.override" && <small>Every use is flagged in the activity log.</small>}
                            </li>
                          ))}
                        </ul>
                      )}
                      {listed.length > 0 && (
                        <div className="cap-chips">
                          <span className="cap-sub">{g.key === "reports" ? "Reports you can open" : "Also"}</span>
                          {listed.map((p) => <span key={p.key} className="cap-chip" title={p.help}>{p.label}</span>)}
                        </div>
                      )}
                    </section>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Security</h2>
          <span className="hint">
            Last signed in: {profile.last_login ? fmtDateTime(profile.last_login) : "never"}
          </span>
        </div>
        <div className="card-body">
          <Message kind="info">
            <b>Your password is your signature.</b> Anything you sign is recorded as personally
            approved by you, so never share it or let someone else use your account. Nobody else
            should know it: a password an administrator sets is only good until you choose your own.
          </Message>
          <div style={{ marginTop: 16, maxWidth: 420 }}>
            <PasswordForm />
          </div>
        </div>
      </div>
    </>
  );
}
