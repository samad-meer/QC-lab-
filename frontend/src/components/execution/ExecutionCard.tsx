import { useEffect, useState } from "react";
import type { Execution } from "../../types";
import HoldBar from "./HoldBar";
import StepPanel from "./StepPanel";
import StepTabs from "./StepTabs";

/** Every step of the journey, one at a time — opening on the step in progress. */
export default function ExecutionCard({
  sampleId,
  exec,
  onChange,
  title = "Step work",
}: {
  sampleId: number;
  exec: Execution;
  onChange: (e: Execution) => void;
  title?: string;
}) {
  const [selected, setSelected] = useState(exec.current_step ?? exec.steps[exec.steps.length - 1].key);

  // Follow the sample when it moves on (a signature elsewhere, a send-back).
  useEffect(() => {
    if (exec.current_step) setSelected(exec.current_step);
  }, [exec.current_step]);

  const step = exec.steps.find((s) => s.key === selected) ?? exec.steps[0];

  return (
    <section className="card" aria-label={title}>
      <div className="card-head">
        <h2>{title}</h2>
        <span className="hint">Checklists, files, notes and handovers — each with who and exactly when</span>
        <div className="spacer" />
        <HoldBar sampleId={sampleId} exec={exec} onChange={onChange} variant="button" />
      </div>
      <div className="card-body">
        <StepTabs steps={exec.steps} selected={step.key} onSelect={setSelected} />
        <StepPanel sampleId={sampleId} exec={exec} step={step} onChange={onChange} />
      </div>
    </section>
  );
}
