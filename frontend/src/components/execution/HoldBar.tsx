import { useState } from "react";
import { apiPost } from "../../api";
import type { Execution } from "../../types";
import CommentModal from "../CommentModal";
import Stamp from "../Stamp";
import { useToast } from "../Toast";

/**
 * A sample on hold, said loudly ("banner") — or, for someone allowed to,
 * the button that puts it on hold ("button"). Both directions need a reason.
 */
export default function HoldBar({
  sampleId,
  exec,
  onChange,
  variant,
}: {
  sampleId: number;
  exec: Execution;
  onChange: (e: Execution) => void;
  variant: "banner" | "button";
}) {
  const toast = useToast();
  const [modal, setModal] = useState<"hold" | "release" | null>(null);
  const hold = exec.hold;

  let body = null;
  if (variant === "banner" && hold) {
    body = (
      <div className="hold-bar" role="status">
        <span className="hold-icon" aria-hidden="true">❚❚</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <b>On hold — nothing can be entered or signed</b>
          <div>“{hold.reason}”</div>
          <div className="cell-sub"><Stamp at={hold.placed_at} by={hold.placed_by} verb="placed by" /></div>
        </div>
        {exec.can_hold && <button className="primary small" onClick={() => setModal("release")}>Release…</button>}
      </div>
    );
  } else if (variant === "button" && !hold && exec.can_hold) {
    body = <button className="ghost small" onClick={() => setModal("hold")}>❚❚ Put on hold…</button>;
  }

  return (
    <>
      {body}
      {modal === "hold" && (
        <CommentModal
          title="Put this sample on hold"
          hint="Everyone working on it will see your reason. Nothing can be entered or signed until someone releases it."
          label="Why is work stopping?"
          confirmText="Put on hold"
          placeholder="e.g. Reference standard expired — waiting for the new lot."
          onConfirm={async (reason) => {
            onChange(await apiPost<Execution>(`/api/samples/${sampleId}/hold/`, { reason }));
            setModal(null);
            toast("info", "Sample on hold");
          }}
          onClose={() => setModal(null)}
        />
      )}
      {modal === "release" && (
        <CommentModal
          title="Release from hold"
          label="What was resolved?"
          confirmText="Release"
          tone="primary"
          placeholder="e.g. New lot of reference standard received and qualified."
          onConfirm={async (comment) => {
            onChange(await apiPost<Execution>(`/api/samples/${sampleId}/hold/`, { release: true, comment }));
            setModal(null);
            toast("ok", "Released — work can continue");
          }}
          onClose={() => setModal(null)}
        />
      )}
    </>
  );
}
