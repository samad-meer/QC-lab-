import type { Certificate } from "../types";
import SignatureGrid, { initials } from "./SignatureGrid";

/** The orbs of the people who have signed, the one whose turn it is, and those to come. */
export function SignOrbs({ chain, awaitingCode }: { chain: Certificate["chain"]; awaitingCode: string }) {
  return (
    <>
      {chain.map((row, i) => {
        const signed = !!row.name_snapshot;
        const current = !signed && row.code === awaitingCode;
        return (
          <span key={row.code} className={`dock-orb ${signed ? "done" : current ? "current" : "future"}`} aria-hidden="true">
            {signed ? initials(row.name_snapshot!) : current ? "You" : i + 1}
          </span>
        );
      })}
    </>
  );
}

/**
 * Who has signed this certificate and who is next. The same person cannot sign twice, so
 * every signature is a different person.
 */
export default function SignatureChainCard({ cert }: { cert: Certificate }) {
  return (
    <section className="card" aria-label="Signature chain">
      <div className="card-head">
        <h2>Signature chain</h2>
        <span className="hint">{cert.chain.length} different people, enforced</span>
      </div>
      <div className="card-body">
        <SignatureGrid chain={cert.chain} awaitingCode={cert.awaiting_stage?.code ?? null} mine={cert.my_turn} />
      </div>
    </section>
  );
}
