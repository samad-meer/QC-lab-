import { forwardRef, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Certificate, ChainRow, Execution, SampleDetail } from "../types";
import { fmtDateTime } from "../util";
import StepPanel from "./execution/StepPanel";
import type { JourneyStep } from "./Stepper";

const STATE: Record<JourneyStep["state"], string> = { done: "Done", current: "In progress", future: "Not yet" };

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="jd-fact">
      <small>{label}</small>
      <span>{children}</span>
    </div>
  );
}

/** A signature the step needs: who gave it and when, or who it waits for. */
function SignatureFact({ row, waiting, after }: { row: ChainRow | undefined; waiting: boolean; after?: string }) {
  if (!row) return null;
  const meaning = row.holder ? `${row.title} (${row.holder})` : row.title;
  return (
    <>
      <Fact label="Signature">{meaning}</Fact>
      {row.signed_at ? (
        <Fact label="Signed">
          <b>{row.name_snapshot}</b> · {fmtDateTime(row.signed_at)}
        </Fact>
      ) : (
        <Fact label="Signed">
          <span className="jd-muted">{waiting ? `Not yet — waiting for ${row.holder || row.title}` : after ? `Not yet — comes after ${after}` : "Not yet"}</span>
        </Fact>
      )}
    </>
  );
}

/**
 * One step of the review journey opened up: who did it and when, and the checks, files, notes and
 * history kept against it. Any step can be opened, done or not, so a reviewer can look back over the
 * receipt, the testing and the reviews before theirs, and see what the ones after will need. What may
 * be done on a step (take it, assign it, add a note) is still decided by the server, step by step.
 */
const JourneyStepCard = forwardRef<HTMLElement, {
  steps: JourneyStep[];
  selected: string;
  onSelect: (key: string) => void;
  mine: boolean;
  sample: SampleDetail;
  cert: Certificate;
  exec: Execution | null;
  onExec: (e: Execution) => void;
  /** Buttons for the card's head, e.g. putting the sample on hold. */
  actions?: ReactNode;
}>(function JourneyStepCard({ steps, selected, onSelect, mine, sample, cert, exec, onExec, actions }, ref) {
  const index = Math.max(0, steps.findIndex((s) => s.key === selected));
  const step = steps[index];
  const before = index > 0 ? steps[index - 1] : undefined;
  const stage = step.key.startsWith("stage-") ? cert.stages[Number(step.key.slice(6)) - 1] : undefined;
  const execKey = step.key === "received" ? "RECEIPT" : step.key === "tested" ? "TESTING" : stage?.code;
  const execStep = execKey ? exec?.steps.find((s) => s.key === execKey) : undefined;
  const yours = step.state === "current" && mine;
  const tests = cert.content.tests;
  const failing = tests.filter((t) => t.outcome === "FAIL").length;

  return (
    <section className="card journey-detail" ref={ref} aria-label="Step details">
      <div className="card-head">
        <h2>“{step.label}”{yours ? " — waiting on you" : ` — ${STATE[step.state].toLowerCase()}`}</h2>
        <span className="hint">Open any step: who did it and when, with its checks, files and notes</span>
        <div className="spacer" />
        {actions}
      </div>
      <div className="card-body">
        <div className="step-tabs" role="tablist" aria-label="Journey steps">
          {steps.map((s, i) => (
            <button key={s.key} type="button" role="tab" aria-selected={s.key === step.key}
              className={`step-tab ${s.key === step.key ? "on" : ""}`} onClick={() => onSelect(s.key)}>
              <span className={`step-dot ${s.state === "done" ? "done" : s.state === "current" ? (mine ? "hot" : "now") : ""}`}
                aria-hidden="true">
                {s.state === "done" ? "✓" : i + 1}
              </span>
              <span>
                <b>{s.label}</b>
                <small>{s.state === "current" && mine ? "Waiting on you" : STATE[s.state]}</small>
              </span>
            </button>
          ))}
        </div>

        <div className="jd-facts">
          {step.key === "received" && (
            <>
              <Fact label="Received">{fmtDateTime(sample.received_at)}</Fact>
              <Fact label="From">{sample.received_from || "—"}</Fact>
              <Fact label="Registered by">{sample.registered_by_name || "—"}</Fact>
              <Fact label="Quantity">{sample.quantity || "—"}</Fact>
            </>
          )}
          {step.key === "tested" && (
            <>
              <SignatureFact row={cert.chain[0]} waiting={step.state === "current"} />
              <Fact label="Results">
                {tests.length} on {sample.specification.label}
                {failing > 0 ? <> · <b className="jd-bad">{failing} out of specification</b></> : " · all within limits"}
              </Fact>
            </>
          )}
          {stage && (
            <SignatureFact row={cert.chain.find((r) => r.code === stage.code)} waiting={step.state === "current"}
              after={before?.label} />
          )}
          {step.key === "printed" && (
            <>
              <Fact label="Certificate">
                Version {cert.version} · {cert.status === "APPROVED" ? "approved" : cert.status.replaceAll("_", " ").toLowerCase()}
              </Fact>
              <Fact label="Printed">
                {cert.prints.length === 0 ? (
                  <span className="jd-muted">
                    {cert.status === "APPROVED" ? "Not yet — ready to print" : "Not yet — printing opens once the last signature is in"}
                  </span>
                ) : (
                  cert.prints.map((p) => (
                    <span key={p.copy_number} className="jd-line">
                      Copy {p.copy_number} — <b>{p.printed_by_name}</b> · {fmtDateTime(p.printed_at)}
                    </span>
                  ))
                )}
              </Fact>
            </>
          )}
        </div>

        {step.key === "tested" && (
          <p className="jd-note">
            Each result against its limit is in <a href="#results">Results against limits</a> above, as frozen when the
            analyst signed.
          </p>
        )}
        {step.key === "printed" && cert.status === "APPROVED" && (
          <p className="jd-note"><Link to={`/certificates/${cert.id}`}>Open the certificate →</Link></p>
        )}

        {exec && execStep ? (
          <StepPanel key={execStep.key} sampleId={sample.id} exec={exec} step={execStep} onChange={onExec} />
        ) : step.key === "received" ? (
          <p className="jd-note">This sample's workflow asks for no receipt checks: testing could start as soon as it arrived.</p>
        ) : execKey && !exec ? (
          <p className="jd-note">Loading this step's checks, files and notes…</p>
        ) : null}
      </div>
    </section>
  );
});

export default JourneyStepCard;
