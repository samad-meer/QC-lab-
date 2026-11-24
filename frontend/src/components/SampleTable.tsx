import { useNavigate } from "react-router-dom";
import type { SampleListItem } from "../types";
import type { DateField } from "../useList";
import { daysUntil, fmtDate } from "../util";
import PersonChip from "./PersonChip";
import { SampleStatusBadge } from "./StatusBadge";

/** The dates any list of samples can be filtered on. */
export const SAMPLE_DATE_FIELDS: DateField[] = [
  { key: "received", label: "Received date" },
  { key: "due", label: "Due date" },
];

function DueCell({ due, done }: { due: string; done: boolean }) {
  const days = daysUntil(due);
  if (done || days > 2) return <>{fmtDate(due)}</>;
  return (
    <span className={`badge ${days < 0 ? "fail" : "warn"}`}>
      {fmtDate(due)} · {days < 0 ? `${-days}d late` : days === 0 ? "today" : `${days}d`}
    </span>
  );
}

export default function SampleTable({
  samples,
  highlight,
}: {
  samples: SampleListItem[];
  /** Rows that are waiting for the current user (reviewers: their turn). */
  highlight?: (s: SampleListItem) => boolean;
}) {
  const navigate = useNavigate();

  const open = (s: SampleListItem) => {
    // Send the user to the review screen only if it is theirs to act on:
    // waiting at a stage their role signs.
    navigate(s.my_turn ? `/samples/${s.id}/review` : `/samples/${s.id}`);
  };

  return (
    <div className="table-wrap">
      <table className="grid">
        <thead>
          <tr>
            <th>Sample No</th>
            <th>Product</th>
            <th>Batch / reference</th>
            <th>Analyst</th>
            <th>Due</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {samples.map((s) => (
            <tr
              key={s.id}
              className={`clickable ${(highlight ? highlight(s) : s.my_turn) ? "mine" : ""}`}
              tabIndex={0}
              onClick={() => open(s)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  open(s);
                }
              }}
            >
              <td className="num">{s.sample_no}</td>
              <td>
                <div className="cell-title">{s.product_name}</div>
                <div className="cell-sub">{s.product_code} · {s.section_code}</div>
              </td>
              <td>{s.batch_label}</td>
              <td><PersonChip id={s.assigned_analyst_id} name={s.analyst_name} role="Analyst" /></td>
              <td><DueCell due={s.due_date} done={["APPROVED", "REJECTED", "CANCELLED"].includes(s.status)} /></td>
              <td>
                <SampleStatusBadge
                  status={s.status}
                  label={
                    (highlight ? highlight(s) : s.my_turn)
                      ? s.status === "IN_REVIEW" ? "Your turn to sign" : "Your turn to test"
                      : s.status_label
                  }
                  hot={highlight ? highlight(s) : s.my_turn}
                />
                {s.has_failures && !["APPROVED", "REJECTED", "CANCELLED"].includes(s.status) && (
                  <> <span className="badge fail">OOS</span></>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
