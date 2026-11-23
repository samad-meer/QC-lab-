import { useState } from "react";
import type { FormEvent } from "react";
import { apiPost } from "../api";
import { useAuth } from "../auth";
import { Message } from "./Feedback";

/** A person's own password. Nobody else knows it, which is what makes it a signature. */
export default function PasswordForm({ onDone }: { onDone?: () => void }) {
  const { refreshUser } = useAuth();
  const [form, setForm] = useState({ current: "", next: "", again: "" });
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setDone(false);
    if (form.next !== form.again) {
      setError("The two new passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await apiPost("/api/auth/change-password/", { current_password: form.current, new_password: form.next });
      setForm({ current: "", next: "", again: "" });
      setDone(true);
      await refreshUser();
      onDone?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the password.");
    }
    setBusy(false);
  };

  return (
    <form className="stack" onSubmit={(e) => void submit(e)}>
      {error && <Message kind="error">{error}</Message>}
      {done && <Message kind="info">Your password has been changed.</Message>}
      <label className="field">
        Current password
        <input type="password" required autoComplete="current-password" value={form.current}
          onChange={(e) => set("current", e.target.value)} />
      </label>
      <label className="field">
        New password <span className="note">at least 10 characters, not one you used recently</span>
        <input type="password" required minLength={10} autoComplete="new-password" value={form.next}
          onChange={(e) => set("next", e.target.value)} />
      </label>
      <label className="field">
        New password again
        <input type="password" required minLength={10} autoComplete="new-password" value={form.again}
          onChange={(e) => set("again", e.target.value)} />
      </label>
      <div className="actions-bar" style={{ justifyContent: "flex-end" }}>
        <button type="submit" className="primary" disabled={busy}>{busy ? "Saving…" : "Change password"}</button>
      </div>
    </form>
  );
}
