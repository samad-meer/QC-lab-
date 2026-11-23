import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Message } from "./Feedback";
import ModalBackdrop from "./ModalBackdrop";

interface Props {
  title: string;
  meaning: string; // e.g. "Analysed by"
  description: string;
  onConfirm: (password: string) => Promise<void>;
  onClose: () => void;
}

/**
 * E-signature: the signer re-enters their password at the moment of signing.
 * This is a deliberate legal act, not a convenience click.
 */
export default function SignModal({ title, meaning, description, onConfirm, onClose }: Props) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onConfirm(password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signing failed.");
      setPassword("");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <h3>{title}</h3>
        <div className="sign-meaning">
          <span aria-hidden="true">✎</span>
          <span>You are signing as “{meaning}”</span>
        </div>
        <p className="modal-sub">
          {description} Once signed, this record is permanent — it can never be edited by anyone,
          and your name and the exact time stay on it.
        </p>
        <form onSubmit={submit} className="stack">
          <label className="field">
            Re-enter your password to sign
            <input
              type="password"
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          {error && <Message kind="error">{error}</Message>}
          <div className="actions">
            <button type="button" className="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="primary" disabled={busy || !password}>
              {busy ? "Signing…" : "Sign"}
            </button>
          </div>
        </form>
      </div>
    </ModalBackdrop>
  );
}
