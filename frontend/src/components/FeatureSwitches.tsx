import { useEffect, useState } from "react";
import { apiGet, apiPut } from "../api";
import { useAuth } from "../auth";
import type { FeatureModule, LabFeatures } from "../types";
import { Message } from "./Feedback";
import { useToast } from "./Toast";

/**
 * What the lab shows. A module, or one part of it, switched off for everyone,
 * administrators too, until the lab needs it. Saved the moment it is switched;
 * nothing hidden is deleted, and showing it again brings it back as it was.
 */
export default function FeatureSwitches() {
  const toast = useToast();
  const { refreshUser } = useAuth();
  const [data, setData] = useState<LabFeatures | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet<LabFeatures>("/api/auth/lab/features/")
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load what the lab shows."));
  }, []);

  if (!data) return error ? <Message kind="error">{error}</Message> : null;
  const hidden = new Set<string>(data.hidden);

  const save = async (keys: string[], show: boolean, what: string) => {
    const next = new Set(hidden);
    keys.forEach((k) => (show ? next.delete(k) : next.add(k)));
    setBusy(true);
    setError("");
    try {
      setData(await apiPut<LabFeatures>("/api/auth/lab/features/", { hidden: [...next] }));
      toast("ok", `${what} ${show ? "shown" : "hidden"}`, "For everyone, from their next page.");
      await refreshUser(); // so this menu changes at once
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  };

  const everyKey = data.modules.flatMap((m) => [...(m.whole ? [m.whole] : []), ...m.parts.map((p) => p.key)]);

  return (
    <div className="card">
      <div className="card-head">
        <h2>Features shown</h2>
        <span className="hint">Switch off what the lab does not use yet. Nothing is deleted.</span>
        <div className="spacer" />
        {hidden.size > 0 && (
          <button className="subtle small" disabled={busy} onClick={() => void save(everyKey, true, "Everything")}>
            Show everything
          </button>
        )}
      </div>
      <div className="card-body">
        <p className="cell-sub" style={{ marginTop: 0 }}>
          A hidden feature is gone from the menus, lists and links of everyone, administrators too, and the server
          refuses it. Its records and the rules about them stay as they were. Who may use a feature once it is
          shown is still set per role on the Roles screen.
        </p>
        {error && <div style={{ marginBottom: 12 }}><Message kind="error">{error}</Message></div>}
        {data.modules.map((m) => (
          <FeatureModuleSwitches key={m.key} module={m} hidden={hidden} busy={busy} onSave={save} />
        ))}
      </div>
    </div>
  );
}

function FeatureModuleSwitches({ module: m, hidden, busy, onSave }: {
  module: FeatureModule;
  hidden: Set<string>;
  busy: boolean;
  onSave: (keys: string[], show: boolean, what: string) => Promise<void>;
}) {
  const partKeys = m.parts.map((p) => p.key as string);
  // A module with a permission of its own is switched as a whole; one without is shown while any part is.
  const on = m.whole ? !hidden.has(m.whole) : partKeys.some((k) => !hidden.has(k));
  const shown = partKeys.filter((k) => !hidden.has(k)).length;
  const groups = [...new Set(m.parts.map((p) => p.group))];
  const locked = Boolean(m.whole) && !on;

  return (
    <section className="feature-module" aria-label={m.name}>
      <div className="feature-head">
        <div>
          <b>{m.name}</b>
          <span className="cell-sub">{m.help}</span>
        </div>
        <label className="switch-field">
          <span>{on ? `Shown · ${shown} of ${partKeys.length}` : "Hidden"}</span>
          <input type="checkbox" role="switch" className="switch" checked={on} disabled={busy}
            aria-label={`Show ${m.name}`}
            onChange={(e) => void onSave(m.whole ? [m.whole] : partKeys, e.target.checked, m.name)} />
        </label>
      </div>
      <div className={`feature-parts${locked ? " off" : ""}`}>
        {locked && <p className="perm-note">Hidden with {m.name}. Show {m.name} to choose its parts.</p>}
        {groups.map((g) => (
          <div key={g || "all"} className="perm-group">
            {g && <div className="perm-group-title">{g}</div>}
            <div className="perm-grid">
              {m.parts.filter((p) => p.group === g).map((p) => {
                const partOn = !hidden.has(p.key);
                return (
                  <label key={p.key} className={`feature-part${partOn ? "" : " is-off"}`}>
                    <span>{p.label}</span>
                    <input type="checkbox" role="switch" className="switch" checked={partOn}
                      disabled={busy || locked} aria-label={`Show ${p.label}`}
                      onChange={(e) => void onSave([p.key], e.target.checked, p.label)} />
                  </label>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
