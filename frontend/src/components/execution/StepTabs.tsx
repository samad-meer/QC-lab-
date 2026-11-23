import type { StepView } from "../../types";

const DOT: Record<string, string> = {
  PASSED: "done",
  SUBMITTED: "done",
  COMPLETED: "done",
  IN_PROGRESS: "now",
  REOPENED: "now",
  AWAITING_ACCEPTANCE: "hot",
  FAILED: "bad",
  DECLINED: "bad",
  RETURNED: "bad",
  ON_HOLD: "hold",
};

/** The journey's steps as tabs, each with its live state. */
export default function StepTabs({
  steps,
  selected,
  onSelect,
}: {
  steps: StepView[];
  selected: string;
  onSelect: (key: string) => void;
}) {
  return (
    <div className="step-tabs" role="tablist" aria-label="Steps">
      {steps.map((s) => (
        <button
          key={s.key}
          type="button"
          role="tab"
          aria-selected={s.key === selected}
          className={`step-tab ${s.key === selected ? "on" : ""}`}
          onClick={() => onSelect(s.key)}
        >
          <span className={`step-dot ${DOT[s.status] ?? ""}`} aria-hidden="true">
            {DOT[s.status] === "done" ? "✓" : s.kind === "receipt" ? "☑" : s.order === 0 ? "✎" : s.order}
          </span>
          <span>
            <b>{s.name}</b>
            <small>{s.status_label}</small>
          </span>
          {s.checklist.length > 0 && <span className="tag soft">{s.checklist.length}</span>}
        </button>
      ))}
    </div>
  );
}
