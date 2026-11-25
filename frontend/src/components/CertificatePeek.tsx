import { Link } from "react-router-dom";
import type { Certificate } from "../types";

/**
 * The certificate this sample is working toward, one click away: a small paper beside
 * the journey, and a link to open it exactly as it will print.
 */
export default function CertificatePeek({ cert }: { cert: Certificate }) {
  const released = cert.status === "APPROVED";
  return (
    <aside className="card cert-peek" aria-label={`Certificate v${cert.version}`}>
      <div className="cert-peek-paper" aria-hidden="true">
        <i className="bar dark" />
        <i className="bar" />
        <span className="lines"><i /><i /><i /></span>
        <span className="rules"><i className="ok" /><i className="ok" /><i className={released ? "ok" : "open"} /></span>
        <span className="qr" />
      </div>
      <div className="cert-peek-text">
        <h2>Certificate v{cert.version}</h2>
        <p>
          {released
            ? "Released. Opens exactly as it prints, with its QR verification."
            : "Opens exactly as it will print — with QR verification."}
        </p>
        <Link to={`/certificates/${cert.id}`} className="btn-link">Preview certificate →</Link>
      </div>
    </aside>
  );
}
