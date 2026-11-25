import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { BatchDetail } from "../types";
import LineIcon from "./LineIcon";

type Stage = NonNullable<BatchDetail["qc_stages"]>["stages"][number];
type State = "done" | "failed" | "doing" | "ready" | "waiting" | "skipped" | "held";

interface Step {
  key: string;
  /** The stage on the page below, to bring into view; none for the release. */
  stageId: number | null;
  mark: string;
  name: string;
  state: State;
  label: string;
  detail: string;
  optional: boolean;
}

function stageStep(s: Stage): Step {
  const holder = s.assignment?.holder?.name;
  const base = { key: `stage-${s.id}`, stageId: s.id, mark: String(s.order), name: s.name, optional: !s.required };
  switch (s.status) {
    case "PASSED":
      return { ...base, state: "done", label: "Passed", detail: "" };
    case "FAILED":
      return { ...base, state: "failed", label: "Failed", detail: "" };
    case "IN_PROGRESS":
      return { ...base, state: "doing", label: "In progress", detail: holder ? `With ${holder}` : "" };
    case "NOT_APPLICABLE":
      return { ...base, state: "skipped", label: "Does not apply", detail: "" };
    default:
      return s.waiting_for.length > 0
        ? { ...base, state: "waiting", label: "Waiting", detail: `For ${s.waiting_for.join(", ")}` }
        : { ...base, state: "ready", label: "Ready to start", detail: holder ? `For ${holder}` : "" };
  }
}

/** The last step: the batch's release, once its stages allow it. */
function releaseStep(batch: BatchDetail): Step {
  const base = { key: "release", stageId: null, mark: "", name: "Release", optional: false };
  const view = batch.qc_stages;
  switch (batch.disposition.decision) {
    case "RELEASED":
      return { ...base, state: "done", label: "Released", detail: "" };
    case "REJECTED":
      return { ...base, state: "failed", label: "Rejected", detail: "" };
    case "QUARANTINED":
      return { ...base, state: "held", label: "Quarantined", detail: "" };
    default:
      return view && view.passed === view.required
        ? { ...base, state: "ready", label: "Ready for a decision", detail: "" }
        : { ...base, state: "waiting", label: "Not decided", detail: "Waits for the required stages" };
  }
}

const ICON: Partial<Record<State, "check" | "close" | "pause">> = { done: "check", failed: "close", held: "pause" };

/**
 * Where a batch stands, at a glance: each QC stage as a step, done, in progress or
 * waiting, and its release at the end. A step opens its stage on the page below.
 */
export default function BatchProgress({ batch, forStageId }: {
  batch: BatchDetail;
  /**
   * Shown on a sample's page, not the batch's: the QC stage that sample was taken for (null for
   * none) is marked, and a step opens that stage on the batch page. Left out, it is the batch's own.
   */
  forStageId?: number | null;
}) {
  const view = batch.qc_stages;
  const navigate = useNavigate();
  const list = useRef<HTMLOListElement>(null);
  const forSample = forStageId !== undefined;
  // A long run of stages scrolls: bring this sample's stage to the middle of the strip.
  useEffect(() => {
    const strip = list.current;
    const mark = strip?.querySelector<HTMLElement>(".for-sample");
    if (strip && mark) {
      strip.scrollLeft += mark.getBoundingClientRect().left - strip.getBoundingClientRect().left - (strip.clientWidth - mark.offsetWidth) / 2;
    }
  }, [forStageId, view?.stages.length]);

  if (!view || view.stages.length === 0) return null;
  const steps = [...view.stages.map(stageStep), releaseStep(batch)];
  // Where the batch is now: the first stage being worked on, else the first that can start,
  // else one that failed, else the release.
  const current = steps.find((s) => s.state === "doing")
    ?? steps.find((s) => s.state === "ready")
    ?? steps.find((s) => s.state === "failed")
    ?? steps[steps.length - 1];
  const mine = forSample ? steps.find((s) => s.stageId !== null && s.stageId === forStageId) : undefined;
  const open = (id: number | null) => {
    if (forSample) {
      navigate(`/batches/${batch.id}${id === null ? "" : `#stage-${id}`}`);
      return;
    }
    const el = id === null ? document.querySelector('section[aria-label="Disposition"]') : document.getElementById(`stage-${id}`);
    el?.scrollIntoView({ block: "start", behavior: "smooth" });
  };

  return (
    <section className="card batch-progress" aria-label={forSample ? "QC stages of this batch" : "Where this batch is"}>
      <div className="card-head">
        <h2>{forSample ? `QC stages of batch ${batch.official_batch_no}` : "Where this batch is"}</h2>
        <span className="hint">
          {forSample
            ? mine
              ? `This sample is for stage ${mine.mark}, ${mine.name}: ${mine.label.toLowerCase()}`
              : "This sample was not taken for one stage"
            : current.stageId !== null ? `Now: ${current.mark}. ${current.name}, ${current.label.toLowerCase()}` : `Release: ${current.label.toLowerCase()}`}
          {view.required > 0 && ` · ${view.passed} of ${view.required} required stages passed`}
        </span>
        {forSample && (
          <>
            <div className="spacer" />
            <Link to={`/batches/${batch.id}`} className="btn-link">Open the batch →</Link>
          </>
        )}
      </div>
      <ol className="bp-steps" ref={list} style={{ "--bp-count": steps.length } as CSSProperties}>
        {steps.map((s, i) => (
          <li key={s.key}
            className={`bp-step ${s.state}${!forSample && s === current ? " current" : ""}${s === mine ? " for-sample" : ""}${i > 0 && steps[i - 1].state === "done" ? " after-done" : ""}`}
            aria-current={!forSample && s === current ? "step" : undefined}>
            <button type="button" onClick={() => open(s.stageId)} title={[s.name, s.label, s.detail].filter(Boolean).join(" · ")}>
              <span className="bp-dot" aria-hidden="true">
                {ICON[s.state] ? <LineIcon name={ICON[s.state]!} size={16} /> : s.stageId === null ? <LineIcon name="send" size={15} /> : s.mark}
              </span>
              <span className="bp-text">
                <span className="bp-name">{s.name}{s.optional && <small> optional</small>}</span>
                <span className="bp-state">{s.label}</span>
                {s === mine && <span className="bp-tag">This sample</span>}
                {s.detail && <span className="bp-detail">{s.detail}</span>}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
