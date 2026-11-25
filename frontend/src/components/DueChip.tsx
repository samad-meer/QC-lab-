import { daysUntil, fmtDate } from "../util";

/** A due date as a pill: red with how late once past, amber when due today or tomorrow. */
export default function DueChip({ due, done }: { due: string; done: boolean }) {
  const days = daysUntil(due);
  const late = days < 0 && !done;
  const today = days === 0 && !done;
  return (
    <span className={`tk-due ${late ? "late" : today || (days === 1 && !done) ? "soon" : ""}`}>
      Due {fmtDate(due)}
      {late ? ` · ${-days} day${days === -1 ? "" : "s"} late` : today ? " · today" : ""}
    </span>
  );
}
