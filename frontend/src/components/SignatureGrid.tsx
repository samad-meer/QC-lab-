import type { ChainRow } from "../types";
import { fmtDateTime } from "../util";

export function initials(name: string) {
  const words = name.split(/\s+/).filter((w) => w && !w.endsWith("."));
  return (words.slice(0, 2).map((w) => w[0]).join("") || name.slice(0, 2)).toUpperCase();
}

/**
 * Every signature the certificate needs, in order — as many as its
 * workflow requires. The one being waited for is lit; when it is yours,
 * it glows.
 */
export default function SignatureGrid({
  chain,
  awaitingCode = null,
  mine = false,
}: {
  chain: ChainRow[];
  awaitingCode?: string | null;
  mine?: boolean;
}) {
  return (
    <div className="sig-grid">
      {chain.map((row, i) => {
        const signed = !!row.name_snapshot;
        const awaiting = !signed && row.code === awaitingCode;
        const title = row.holder ? `${row.title} (${row.holder})` : row.title;
        return (
          <div
            key={row.code}
            className={`sig-card ${signed ? "signed" : ""} ${awaiting ? "awaiting" : ""} ${awaiting && mine ? "mine" : ""}`}
          >
            <span className="sig-orb" aria-hidden="true">
              {signed ? initials(row.name_snapshot!) : awaiting && mine ? "You" : i + 1}
            </span>
            <span style={{ minWidth: 0 }}>
              <span className="sig-role" style={{ display: "block" }}>{title}</span>
              {signed ? (
                <>
                  <span className="sig-name" style={{ display: "block" }}>{row.name_snapshot}</span>
                  <span className="sig-when">{row.signed_at ? fmtDateTime(row.signed_at) : ""}</span>
                </>
              ) : (
                <span className="sig-pending">
                  {awaiting ? (mine ? "Your signature" : "Waiting now") : "Not yet signed"}
                </span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}
