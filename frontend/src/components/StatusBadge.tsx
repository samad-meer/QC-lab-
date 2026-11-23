import type { CertStatus, Outcome, SampleStatus } from "../types";

const SAMPLE_LABELS: Record<SampleStatus, [string, string]> = {
  RECEIVED: ["Received", "muted"],
  IN_TESTING: ["In testing", "info"],
  IN_REVIEW: ["In review", "warn"],
  APPROVED: ["Approved", "pass"],
  REJECTED: ["Rejected", "fail"],
  CANCELLED: ["Cancelled", "muted"],
};

const CERT_LABELS: Record<CertStatus, [string, string]> = {
  IN_REVIEW: ["In review", "warn"],
  APPROVED: ["Approved", "pass"],
  SUPERSEDED: ["Superseded", "muted"],
  WITHDRAWN: ["Withdrawn", "fail"],
};

/** `label` is the server's wording, e.g. "Awaiting AM / DM" for a sample in review. */
export function SampleStatusBadge({
  status,
  label: given,
  hot = false,
}: {
  status: SampleStatus;
  label?: string;
  /** Waiting for the person looking at it: the hot colour, pulsing. */
  hot?: boolean;
}) {
  const [fallback, base] = SAMPLE_LABELS[status] ?? [status, "muted"];
  const label = given || fallback;
  const cls = hot ? "hot" : base;
  return (
    <span className={`badge ${cls}`}>
      <span className="dot" aria-hidden="true" />
      {label}
    </span>
  );
}

export function CertStatusBadge({ status }: { status: CertStatus }) {
  const [label, cls] = CERT_LABELS[status] ?? [status, "muted"];
  return (
    <span className={`badge ${cls}`}>
      <span className="dot" aria-hidden="true" />
      {label}
    </span>
  );
}

export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  if (outcome === "PASS") return <span className="badge pass">Pass</span>;
  if (outcome === "FAIL") return <span className="badge fail">Fail</span>;
  return <span className="badge muted">Reported</span>;
}
