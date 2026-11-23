import type { StepStatus } from "../../types";

const TONE: Record<StepStatus, string> = {
  NOT_STARTED: "muted",
  WAITING: "muted",
  COMPLETED: "pass",
  AWAITING_ACCEPTANCE: "hot",
  DECLINED: "fail",
  IN_PROGRESS: "info",
  REOPENED: "warn",
  FAILED: "fail",
  ON_HOLD: "warn",
  SUBMITTED: "pass",
  PASSED: "pass",
  RETURNED: "fail",
};

/** A step's state in the server's own words. */
export default function StepBadge({ status, label }: { status: StepStatus; label: string }) {
  return (
    <span className={`badge ${TONE[status] ?? "muted"}`}>
      <span className="dot" aria-hidden="true" />
      {label}
    </span>
  );
}
