import type { SampleStatus, WorkflowStage } from "../types";

/**
 * The journey, made visible: where this sample has got to, and which of
 * the remaining steps are signatures. Receipt, testing and printing are
 * the same for every sample; the review steps between them are the ones
 * its product's workflow requires — one, two, or more.
 */
export interface JourneyStep {
  key: string;
  label: string;
  who: string;
  signature?: boolean;
  state: "done" | "current" | "future";
}

/** How many steps are complete for a given sample state. */
export function completedCount(
  status: SampleStatus,
  reviewStage: number | null,
  reviews: number,
  printed: boolean,
): number {
  switch (status) {
    case "RECEIVED":
    case "IN_TESTING":
      return 1;
    case "IN_REVIEW":
      // Received + tested + the reviews already signed.
      return 1 + (reviewStage ?? 1);
    case "APPROVED":
      return printed ? reviews + 3 : reviews + 2;
    default:
      return 0;
  }
}

/**
 * Every step of the journey with its state. `names` can replace the
 * "who" line step by step — a signer's name instead of their title.
 */
export function journeySteps(
  status: SampleStatus | null,
  stages: WorkflowStage[],
  reviewStage: number | null,
  printed: boolean,
  names: (string | null | undefined)[] = [],
): JourneyStep[] {
  const base = [
    { key: "received", label: "Received", who: "Front desk" },
    { key: "tested", label: "Tested", who: "Analyst", signature: true },
    ...stages.map((s) => ({ key: `stage-${s.order}`, label: s.name, who: s.holder, signature: true })),
    { key: "printed", label: "Printed", who: "Released" },
  ];
  const done = status === null ? -1 : completedCount(status, reviewStage, stages.length, printed);
  return base.map((s, i) => ({
    ...s,
    who: names[i] || s.who,
    state: done < 0 ? "future" : i < done ? "done" : i === done ? "current" : "future",
  }));
}

export default function Stepper({
  status,
  stages,
  reviewStage = null,
  printed = false,
  mine = false,
}: {
  /** null previews the chain without marking any step — the workflow editor. */
  status: SampleStatus | null;
  stages: WorkflowStage[];
  /** While IN_REVIEW: the 1-based stage the sample waits at. */
  reviewStage?: number | null;
  printed?: boolean;
  /** The current step is waiting for the person looking at it. */
  mine?: boolean;
}) {
  const steps = journeySteps(status, stages, reviewStage, printed);

  return (
    <div className="stepper" role="list" aria-label="Sample progress">
      {steps.map((s, i) => (
        <div
          key={s.key}
          className={`step ${s.state === "future" ? "" : s.state} ${s.signature ? "sig" : ""}`}
          role="listitem"
          aria-current={s.state === "current" ? "step" : undefined}
        >
          <div className="step-dot">
            {s.state === "done" ? "✓" : s.state === "current" && mine ? "You" : i + 1}
          </div>
          <div className="step-label">{s.label}</div>
          <div className="step-who">{s.state === "current" && mine ? "Waiting on you" : s.who}</div>
        </div>
      ))}
    </div>
  );
}
