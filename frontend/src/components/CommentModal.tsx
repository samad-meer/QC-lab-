import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Message } from "./Feedback";
import ModalBackdrop from "./ModalBackdrop";

interface Props {
  title: string;
  label: string;
  confirmText: string;
  hint?: string;
  /** Let the person confirm without writing anything. */
  optional?: boolean;
  /** "danger" for send-backs and refusals; "primary" for ordinary steps forward. */
  tone?: "danger" | "primary";
  placeholder?: string;
  /** Anything else the person must decide, above the comment. */
  children?: ReactNode;
  onConfirm: (comment: string) => Promise<void>;
  onClose: () => void;
}

/** A reason that becomes part of the record — mandatory unless `optional`. */
export default function CommentModal({
  title,
  label,
  confirmText,
  hint,
  optional = false,
  tone = "danger",
  placeholder = "Be specific — this stays on the record and the next person will read it.",
  children,
  onConfirm,
  onClose,
}: Props) {
  const [comment, setComment] = useState("");
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
      await onConfirm(comment.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed.");
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
        {hint && <p className="modal-sub">{hint}</p>}
        <form onSubmit={submit} className="stack">
          {children}
          <label className="field">
            {label}
            <textarea
              rows={4}
              autoFocus
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder={placeholder}
            />
          </label>
          {error && <Message kind="error">{error}</Message>}
          <div className="actions">
            <button type="button" className="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className={tone} disabled={busy || (!optional && !comment.trim())}>
              {busy ? "Sending…" : confirmText}
            </button>
          </div>
        </form>
      </div>
    </ModalBackdrop>
  );
}
