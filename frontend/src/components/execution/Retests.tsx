import { useState } from "react";
import { apiPost } from "../../api";
import { useAuth } from "../../auth";
import type { Execution, RetestView } from "../../types";
import CommentModal from "../CommentModal";
import Stamp from "../Stamp";
import { OutcomeBadge } from "../StatusBadge";

const TONE: Record<string, string> = { PENDING: "hot", AUTHORIZED: "info", DECLINED: "fail", USED: "pass" };

/**
 * Every retest asked for on this sample, and its decision. Someone with
 * the permission — never the analyst who asked — authorizes or declines.
 */
export default function Retests({
  exec,
  analystId,
  onChange,
}: {
  exec: Execution;
  analystId: number;
  onChange: (e: Execution) => void;
}) {
  const { user, can } = useAuth();
  const [deciding, setDeciding] = useState<{ r: RetestView; authorize: boolean } | null>(null);

  if (exec.retests.length === 0) return null;
  const mayDecide = (r: RetestView) =>
    exec.can_authorize_retests && r.status === "PENDING" && user !== null &&
    (can("admin.override") || ![r.requested_by.id, r.failed_entered_by.id, analystId].includes(user.id));

  return (
    <div className="card">
      <div className="card-head">
        <h2>Retests of failed results</h2>
        <span className="hint">A failed result is never replaced without an independent authorization</span>
      </div>
      <div className="card-body flush">
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr><th>Test</th><th>Failed result</th><th>Why a retest</th><th>Decision</th><th>Retest</th></tr>
            </thead>
            <tbody>
              {exec.retests.map((r) => (
                <tr key={r.id}>
                  <td className="cell-title">{r.test_name}</td>
                  <td>
                    <span className="num">{r.failed_value}</span> <span className="badge fail">Fail</span>
                    <div className="cell-sub"><Stamp at={r.failed_entered_at} by={r.failed_entered_by} /></div>
                  </td>
                  <td>
                    <span className="badge muted">{r.kind_label}</span> “{r.reason}”
                    <div className="cell-sub"><Stamp at={r.requested_at} by={r.requested_by} verb="asked by" /></div>
                  </td>
                  <td>
                    <span className={`badge ${TONE[r.status]}`}>{r.status_label}</span>
                    {r.decided_at && <div className="cell-sub"><Stamp at={r.decided_at} by={r.decided_by} /></div>}
                    {r.decision_comment && <div className="cell-sub">“{r.decision_comment}”</div>}
                    {mayDecide(r) && (
                      <div className="actions-bar" style={{ marginTop: 8 }}>
                        <button className="danger small" onClick={() => setDeciding({ r, authorize: false })}>Decline…</button>
                        <button className="primary small" onClick={() => setDeciding({ r, authorize: true })}>Authorize…</button>
                      </div>
                    )}
                  </td>
                  <td>
                    {r.retest_value !== null ? (
                      <>
                        <span className="num">{r.retest_value}</span>{" "}
                        {r.retest_outcome && <OutcomeBadge outcome={r.retest_outcome} />}
                        <div className="cell-sub"><Stamp at={r.used_at} /></div>
                      </>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {deciding && (
        <CommentModal
          title={`${deciding.authorize ? "Authorize" : "Decline"} the retest of ${deciding.r.test_name}`}
          hint={
            deciding.authorize
              ? "The analyst may then enter one retest result. The failed result stays on record beside it."
              : "The failed result stands. The analyst will see your reason."
          }
          label={deciding.authorize ? "Comment (optional)" : "Why is it declined?"}
          confirmText={deciding.authorize ? "Authorize retest" : "Decline"}
          optional={deciding.authorize}
          tone={deciding.authorize ? "primary" : "danger"}
          onConfirm={async (comment) => {
            onChange(await apiPost<Execution>(`/api/retests/${deciding.r.id}/decide/`, {
              action: deciding.authorize ? "authorize" : "decline", comment,
            }));
            setDeciding(null);
          }}
          onClose={() => setDeciding(null)}
        />
      )}
    </div>
  );
}
