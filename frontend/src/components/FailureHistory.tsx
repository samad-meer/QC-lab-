import type { CertContent } from "../types";
import { fmtDate } from "../util";

/** What lay behind a passing result. Reviewers see this before they sign, whatever the certificate prints. */
export default function FailureHistory({ content }: { content: CertContent }) {
  const retests = content.history_for_review ?? [];
  const investigations = content.investigations ?? [];
  if (retests.length === 0 && investigations.length === 0) return null;
  return (
    <section className="card" aria-label="What happened before this result">
      <div className="card-head">
        <h2>Before you sign: failures on this sample</h2>
        <span className="hint">The results above are the ones reported. These stay on record.</span>
      </div>
      <div className="card-body flush">
        {retests.length > 0 && (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr><th>Test</th><th>Failed</th><th>Why retested</th><th>Authorized by</th><th>Retest</th></tr>
              </thead>
              <tbody>
                {retests.map((r) => (
                  <tr key={`${r.test}-${r.retest_entered_at}`}>
                    <td>{r.test}</td>
                    <td className="num">{r.original_value}{r.unit ? ` ${r.unit}` : ""}</td>
                    <td>{r.reason}</td>
                    <td>{r.authorized_by}</td>
                    <td className="num">{r.retest_value}{r.unit ? ` ${r.unit}` : ""} ({r.retest_outcome})</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {investigations.length > 0 && (
          <ul style={{ padding: "12px 22px 12px 40px", margin: 0 }}>
            {investigations.map((i) => (
              <li key={i.reference}>
                <b>{i.reference}</b> ({i.kind}), closed {fmtDate(i.closed_at)}{i.conclusion ? `: ${i.conclusion}` : ""}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
