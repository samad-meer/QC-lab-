import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPatch } from "../../api";
import { useAuth } from "../../auth";
import BatchNumbering from "../../components/BatchNumbering";
import BrandMark from "../../components/BrandMark";
import ConfirmModal from "../../components/ConfirmModal";
import FeatureSwitches from "../../components/FeatureSwitches";
import Field from "../../components/Field";
import { Message } from "../../components/Feedback";
import { useToast } from "../../components/Toast";
import type { LabDetails } from "../../types";
import { fmtDateTime, zoneOffset } from "../../util";

const BLANK: LabDetails = {
  lab_name: "", app_tagline: "", company_name: "", address: "", licence_no: "",
  phone: "", email: "", website: "", footer_note: "", time_zone: "Asia/Karachi", time_format: "12h",
  logo_url: null,
};

const PAKISTAN = "Asia/Karachi";

/** What the server accepts as a logo (accounts/photos.py checks the image itself). */
const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp"];

const LOGO_ICONS = {
  upload: "M12 16V4 M7 9l5-5 5 5 M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  remove: "M4 7h16 M10 11v6 M14 11v6 M6 7l1 13h10l1-13 M9 7V4h6v3",
};

function LogoIcon({ d, size = 16 }: { d: string; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function csrf(): string {
  return decodeURIComponent(document.cookie.match(/(?:^|; )csrftoken=([^;]*)/)?.[1] ?? "");
}

/**
 * Settings: the system's name, and the letterhead every certificate is
 * printed under. Presentation only — never what a certificate contains.
 */
export default function Settings() {
  const toast = useToast();
  const { can, refreshConfig } = useAuth();
  const [saved, setSaved] = useState<LabDetails | null>(null);
  const [f, setF] = useState<LabDetails>(BLANK);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [logoBusy, setLogoBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const apply = useCallback((d: LabDetails) => {
    setSaved(d);
    setF(d);
  }, []);

  useEffect(() => {
    apiGet<LabDetails>("/api/auth/lab/")
      .then(apply)
      .catch((err) =>
        setLoadError(err instanceof Error ? err.message : "Could not load the settings."),
      );
  }, [apply]);

  const set = (k: keyof LabDetails, v: string) => setF((p) => ({ ...p, [k]: v }));

  // The time now, in the zone being chosen, so the choice can be checked against a clock.
  const [now, setNow] = useState(() => new Date().toISOString());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date().toISOString()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  // Worked out once: the clock above redraws the page every second.
  const zoneOptions = useMemo(
    () => Intl.supportedValuesOf("timeZone")
      .filter((z) => z !== PAKISTAN)
      .map((z) => ({ value: z, label: `${z.replace(/_/g, " ")} (${zoneOffset(z)})` })),
    [],
  );

  if (loadError) return <Message kind="error">{loadError}</Message>;
  if (!saved) {
    return (
      <div className="card">
        <div className="card-body"><div className="sk" style={{ width: 220, height: 14 }} /></div>
      </div>
    );
  }

  const dirty = (Object.keys(BLANK) as (keyof LabDetails)[]).some(
    (k) => k !== "logo_url" && f[k] !== saved[k],
  );
  const nameMissing = !f.lab_name.trim();

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const { logo_url, ...text } = f;
      void logo_url;
      apply(await apiPatch<LabDetails>("/api/auth/lab/", text));
      // The top bar, the sign-in page and the browser tab pick it up now.
      await refreshConfig();
      toast("ok", "Settings saved", "The new name shows everywhere straight away.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  };

  const uploadLogo = async (file: File) => {
    if (!LOGO_TYPES.includes(file.type)) {
      setError(`“${file.name}” is not a PNG, JPEG or WebP image.`);
      return;
    }
    setLogoBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("logo", file);
      const res = await fetch("/api/auth/lab/logo/upload/", {
        method: "POST", credentials: "same-origin",
        headers: { "X-CSRFToken": csrf() }, body,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail ?? "Upload failed.");
      apply({ ...(data as LabDetails) });
      // The top bar and the sign-in page show it straight away.
      await refreshConfig();
      toast("ok", "Logo updated");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setLogoBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const removeLogo = async () => {
    setLogoBusy(true);
    try {
      const res = await fetch("/api/auth/lab/logo/upload/", {
        method: "DELETE", credentials: "same-origin", headers: { "X-CSRFToken": csrf() },
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail ?? "Could not remove the logo.");
      apply(data as LabDetails);
      await refreshConfig();
      toast("ok", "Logo removed");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove the logo.");
    } finally {
      setLogoBusy(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <h1>Settings</h1>
        <p className="sub">
          The system's name, and the letterhead every certificate is printed under. This is
          presentation only: it never changes which tests, limits or results a certificate carries.
        </p>
      </div>

      {error && <div style={{ marginBottom: 16 }}><Message kind="error">{error}</Message></div>}

      <div className="card">
        <div className="card-head">
          <h2>System name and logo</h2>
          <span className="hint">What everyone sees at the top of every page</span>
        </div>
        <div className="card-body settings-name">
          <div style={{ display: "grid", gap: 15, alignContent: "start" }}>
            <Field
              label="System name"
              required
              error={nameMissing ? "The system needs a name." : undefined}
              hint="Top bar, sign-in page, browser tab, QR verification page and printed certificates"
            >
              <input
                value={f.lab_name}
                maxLength={200}
                onChange={(e) => set("lab_name", e.target.value)}
                placeholder="e.g. Samad Pharma — Quality Control"
              />
            </Field>
            <Field label="Tagline" hint="The small line under the name. Leave empty for none.">
              <input
                value={f.app_tagline}
                maxLength={80}
                onChange={(e) => set("app_tagline", e.target.value)}
                placeholder="e.g. Certificate of Analysis"
              />
            </Field>
            <div className="field">
              <span>Logo</span>
              <span className="note">Beside the name in the top bar and on the sign-in page, and at the top of every certificate</span>
              <div className="settings-logo">
                <button
                  type="button"
                  className={`logo-drop${dragging ? " over" : ""}${f.logo_url ? " filled" : ""}`}
                  disabled={logoBusy}
                  onClick={() => fileRef.current?.click()}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragging(false);
                    const file = e.dataTransfer.files?.[0];
                    if (file) void uploadLogo(file);
                  }}
                  aria-label={f.logo_url ? "Replace the logo" : "Add a logo"}
                  title={f.logo_url ? "Click, or drop an image here, to replace it" : "Click, or drop an image here"}
                >
                  {f.logo_url ? (
                    <img src={f.logo_url} alt="" />
                  ) : (
                    <span className="logo-drop-empty">
                      <LogoIcon d={LOGO_ICONS.upload} size={22} />
                      Add a logo
                      <small>or drop an image here</small>
                    </span>
                  )}
                  {logoBusy && <span className="logo-drop-busy">Working…</span>}
                </button>
                <div className="settings-logo-side">
                  <input
                    ref={fileRef}
                    type="file"
                    accept={LOGO_TYPES.join(",")}
                    hidden
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) void uploadLogo(file);
                    }}
                  />
                  <div className="actions-bar">
                    <button className="ghost small" disabled={logoBusy} onClick={() => fileRef.current?.click()}>
                      <LogoIcon d={LOGO_ICONS.upload} />
                      {f.logo_url ? "Replace" : "Choose a file"}
                    </button>
                    {f.logo_url && (
                      <button className="danger small" disabled={logoBusy} onClick={() => setConfirmRemove(true)}>
                        <LogoIcon d={LOGO_ICONS.remove} />
                        Remove
                      </button>
                    )}
                  </div>
                  <span className="cell-sub">
                    PNG, JPEG or WebP, up to 2 MB. A PNG with a transparent background works best: the
                    checkered box shows where it is see-through.
                  </span>
                </div>
              </div>
              {confirmRemove && (
                <ConfirmModal
                  title="Remove the logo?"
                  confirmText="Remove logo"
                  onConfirm={async () => {
                    await removeLogo();
                    setConfirmRemove(false);
                  }}
                  onClose={() => setConfirmRemove(false)}
                >
                  It leaves the top bar and the sign-in page, and certificates printed after this have no
                  logo. You can add one again at any time.
                </ConfirmModal>
              )}
            </div>
          </div>

          <div className="settings-preview" aria-label="Preview of the top bar">
            <span className="settings-preview-label">Preview</span>
            <div className="settings-preview-bar">
              <BrandMark size={38} />
              <div className="brand-text">
                <b>{f.lab_name.trim() || "Your system name"}</b>
                {f.app_tagline.trim() && <span>{f.app_tagline}</span>}
              </div>
            </div>
            <div className="settings-preview-tab">
              <span className="dot" aria-hidden="true" />
              {f.lab_name.trim() || "Your system name"}
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Letterhead</h2>
          <span className="hint">The top of every printed certificate</span>
        </div>
        <div className="card-body">
          <div style={{ display: "grid", gap: 15, alignContent: "start", minWidth: 0 }}>
            <span className="cell-sub">The logo above prints at the top left, about 22&nbsp;mm tall.</span>
            <Field label="Company name" hint="The heading on the certificate; the system name prints under it">
              <input value={f.company_name} onChange={(e) => set("company_name", e.target.value)} />
            </Field>
            <Field label="Address">
              <textarea rows={2} value={f.address} onChange={(e) => set("address", e.target.value)} />
            </Field>
            <div className="form-row">
              <Field label="Licence / registration number">
                <input value={f.licence_no} onChange={(e) => set("licence_no", e.target.value)} />
              </Field>
              <Field label="Telephone">
                <input value={f.phone} onChange={(e) => set("phone", e.target.value)} />
              </Field>
            </div>
            <div className="form-row">
              <Field label="Email">
                <input type="email" value={f.email} onChange={(e) => set("email", e.target.value)} />
              </Field>
              <Field label="Website">
                <input value={f.website} onChange={(e) => set("website", e.target.value)} />
              </Field>
            </div>
            <Field
              label="Footer note"
              hint="Printed small at the foot of every certificate, above the QR code"
            >
              <textarea
                rows={2}
                value={f.footer_note}
                onChange={(e) => set("footer_note", e.target.value)}
                placeholder="e.g. This certificate relates only to the sample tested."
              />
            </Field>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Date and time</h2>
          <span className="hint">Where “today” begins, and how every time is shown and printed</span>
        </div>
        <div className="card-body settings-name">
          <div style={{ display: "grid", gap: 12, alignContent: "start" }}>
            <Field label="Time zone" hint="Pakistan unless changed">
              <select value={f.time_zone} onChange={(e) => set("time_zone", e.target.value)}>
                <option value={PAKISTAN}>Pakistan — Asia/Karachi ({zoneOffset(PAKISTAN)})</option>
                <optgroup label="Every time zone">
                  {zoneOptions.map((z) => <option key={z.value} value={z.value}>{z.label}</option>)}
                </optgroup>
              </select>
            </Field>
            {/* A div, not a <label>: two buttons, not one input, so each keeps its own name. */}
            <div className="field">
              <span>Clock</span>
              <span className="note">How every time of day is shown and printed</span>
              <div className="seg" role="group" aria-label="Clock" style={{ justifySelf: "start" }}>
                {([["12h", "12-hour · 02:05 PM"], ["24h", "24-hour · 14:05"]] as const).map(([value, label]) => (
                  <button key={value} type="button" className={f.time_format === value ? "on" : ""}
                    aria-pressed={f.time_format === value} onClick={() => set("time_format", value)}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <span className="cell-sub">
              Every time is stored in UTC, so a change moves no recorded time. It changes how times are
              shown and printed from now on, and where “today” begins for due dates, overdue alerts and
              report periods. Certificates already signed keep the times they were signed with.
            </span>
          </div>
          <div className="settings-preview" aria-label="The time now in this zone">
            <span className="settings-preview-label">Now in this zone</span>
            <div className="settings-clock">{fmtDateTime(now, f.time_zone, f.time_format === "12h")}</div>
            <span className="cell-sub">{f.time_zone.replace(/_/g, " ")} · {zoneOffset(f.time_zone)}</span>
          </div>
        </div>
      </div>

      <Message kind="info">
        What each signature is called — “Checked by (AM / DM)”, “Approved by (QCM / HOD)” — belongs
        to its review stage. Set the stages, their titles and who signs them on the{" "}
        <Link to="/admin/workflows">Workflows</Link> screen.
      </Message>

      {dirty && (
        <div className="dock settings-dock" role="region" aria-label="Unsaved changes">
          <span className="dock-text" style={{ marginLeft: 0, flex: 1 }}>
            <b>You have unsaved changes</b>
            <br />
            Certificates already signed keep the details they were issued with.
          </span>
          <button className="ghost" onClick={() => setF(saved)} disabled={busy}>
            Discard
          </button>
          <button className="primary" onClick={() => void save()} disabled={busy || nameMissing}>
            {busy ? "Saving…" : "Save settings"}
          </button>
        </div>
      )}

      <FeatureSwitches />

      <BatchNumbering />

      {can("user.manage") && (
        <Message kind="info">
          Who can sign in, and who is signed in right now, have their own screen:{" "}
          <Link to="/admin/sign-in">Sign-in and sessions</Link>.
        </Message>
      )}
    </>
  );
}
