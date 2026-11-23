import type { PersonRef } from "../types";
import { fmtDateTime } from "../util";

/** Who, and exactly when — the server's time, to the second. */
export default function Stamp({
  at,
  by,
  verb,
}: {
  at: string | null | undefined;
  by?: PersonRef | null;
  verb?: string;
}) {
  if (!at) return null;
  return (
    <span className="stamp">
      {verb && <>{verb} </>}
      {by && <b>{by.name}</b>}
      {by && <span aria-hidden="true"> · </span>}
      <time dateTime={at}>
        {fmtDateTime(at)}
      </time>
    </span>
  );
}
