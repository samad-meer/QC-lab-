import { Link } from "react-router-dom";
import type { ReportCellValue } from "../../types";

/**
 * One value of a report, as the server wrote it. Dates are never reformatted
 * here: every report reads the same, in the lab's time zone, on screen and in
 * every export.
 */
export default function ReportCell({ cell }: { cell: ReportCellValue }) {
  if (typeof cell === "string") return <>{cell || "—"}</>;
  const body = cell.tone ? <span className={`badge ${cell.tone}`}>{cell.text}</span> : cell.text || "—";
  return (
    <>
      {cell.to ? <Link to={cell.to}>{body}</Link> : body}
      {cell.sub && <div className="cell-sub">{cell.sub}</div>}
    </>
  );
}
