import { useState } from "react";
import { apiPost } from "../../api";
import CommentModal from "../CommentModal";
import { useToast } from "../Toast";
import type { Execution } from "../../types";

/** The two ways a sample ends without a certificate. Both are signed acts. */
export default function CloseSample({ sampleId, exec, onChange }: {
  sampleId: number;
  exec: Execution;
  onChange: () => void;
}) {
  const toast = useToast();
  const [action, setAction] = useState<"reject" | "cancel" | null>(null);
  const [password, setPassword] = useState("");

  if (!exec.can_reject && !exec.can_cancel) return null;
  const close = () => {
    setAction(null);
    setPassword("");
  };

  return (
    <>
      {exec.can_cancel && <button className="ghost small" onClick={() => setAction("cancel")}>Cancel sample…</button>}
      {exec.can_reject && <button className="danger small" onClick={() => setAction("reject")}>Reject sample…</button>}
      {action && (
        <CommentModal
          title={action === "reject" ? "Reject this sample" : "Cancel this sample"}
          hint={action === "reject"
            ? "For a failure an investigation has confirmed. This ends the sample, and it blocks certificates for the batch."
            : "For a sample registered by mistake, damaged or not testable. This ends the sample with no result."}
          label="Why?"
          confirmText={action === "reject" ? "Reject sample" : "Cancel sample"}
          onConfirm={async (reason) => {
            await apiPost(`/api/samples/${sampleId}/close/`, { action, reason, password });
            close();
            toast("ok", action === "reject" ? "Sample rejected" : "Sample cancelled", "This cannot be undone.");
            onChange();
          }}
          onClose={close}
        >
          <label className="field">
            Your password <span className="note">this is a signature</span>
            <input type="password" required autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </label>
        </CommentModal>
      )}
    </>
  );
}
