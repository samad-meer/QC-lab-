import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../api";
import type { AuditReviewData } from "../types";
import { fmtDateTime } from "../util";
import CommentModal from "./CommentModal";
import { useToast } from "./Toast";

/** Reviewing the trail is a record of its own. Each review picks up where the last one stopped. */
export default function AuditReviews() {
  const toast = useToast();
  const [data, setData] = useState<AuditReviewData | null>(null);
  const [failed, setFailed] = useState("");
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await apiGet<AuditReviewData>("/api/auth/audit/reviews/"));
      setFailed("");
    } catch (err) {
      setFailed(err instanceof Error ? err.message : "Could not load the reviews.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const close = () => {
    setOpen(false);
    setPassword("");
  };
  const latest = data?.latest;

  return (
    <section className="card" aria-label="Audit trail review">
      <div className="card-head">
        <h2>Review</h2>
        <span className="hint">
          {failed || (latest
            ? `Last reviewed by ${latest.name} on ${fmtDateTime(latest.reviewed_at)}.`
            : "This trail has not been reviewed yet.")}
          {data ? ` ${data.unreviewed} event(s) since.` : ""}
        </span>
        <div className="spacer" />
        {data && <button className="ghost small" onClick={() => setOpen(true)}>Record a review…</button>}
      </div>
      {open && (
        <CommentModal
          title="Record a review of the activity log"
          hint={`This covers the ${data?.unreviewed ?? 0} event(s) since the last review.`}
          label="What did you check, and what did you find?"
          confirmText="Sign the review"
          tone="primary"
          onConfirm={async (findings) => {
            await apiPost("/api/auth/audit/reviews/", { findings, password });
            close();
            toast("ok", "Review recorded", "The next review picks up from now.");
            await load();
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
    </section>
  );
}
