import { useState } from "react";
import type { ReactNode } from "react";
import { Message } from "./Feedback";
import ModalBackdrop from "./ModalBackdrop";

/** Asks once more before something that cannot be taken back. A refusal from the server shows here. */
export default function ConfirmModal({
  title,
  children,
  confirmText,
  cancelText = "Cancel",
  onConfirm,
  onClose,
}: {
  title: string;
  children: ReactNode;
  confirmText: string;
  cancelText?: string;
  onConfirm: () => void | Promise<void>;
  onClose: () => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const confirm = async () => {
    setBusy(true);
    setError("");
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not work.");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        <p className="modal-sub">{children}</p>
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="ghost" disabled={busy} onClick={onClose} autoFocus>{cancelText}</button>
          <button className="danger" disabled={busy} onClick={() => void confirm()}>
            {busy ? "Working…" : confirmText}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}
