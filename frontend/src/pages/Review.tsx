import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import BottleProgress from "../components/BottleProgress";
import CommentModal from "../components/CommentModal";
import HoldBar from "../components/execution/HoldBar";
import OverrideNotice from "../components/execution/OverrideNotice";
import { useExecution } from "../components/execution/useExecution";
import FailureHistory from "../components/FailureHistory";
import JourneyStepCard from "../components/JourneyStepCard";
import { Message, TableSkeleton } from "../components/Feedback";
import ResultGauges from "../components/ResultGauges";
import SampleHero from "../components/SampleHero";
import CertificatePeek from "../components/CertificatePeek";
import SignatureGrid from "../components/SignatureGrid";
import { SignOrbs } from "../components/SignatureChainCard";
import SignModal from "../components/SignModal";
import Stepper, { journeySteps } from "../components/Stepper";
import { useToast } from "../components/Toast";
import type { Certificate, Execution, SampleDetail } from "../types";

function fullTitle(title: string, holder: string) {
  return holder ? `${title} (${holder})` : title;
}

/**
 * The reviewer's screen, for whichever stage of the workflow this
 * certificate is waiting at: each result against its allowed range, the
 * certificate exactly as it was frozen, and the signature waiting on you.
 */
export default function Review() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [sample, setSample] = useState<SampleDetail | null>(null);
  const [cert, setCert] = useState<Certificate | null>(null);
  const [modal, setModal] = useState<"sign" | "back" | null>(null);
  const [loadError, setLoadError] = useState("");
  const { exec, setExec, error: execError } = useExecution(id);
  // The journey step opened below; until one is picked, the step the sample is at.
  const [viewing, setViewing] = useState<string | null>(null);
  const detailRef = useRef<HTMLElement>(null);

  const load = useCallback(async () => {
    try {
      const s = await apiGet<SampleDetail>(`/api/samples/${id}/`);
      setSample(s);
      const latest = s.certificates[s.certificates.length - 1];
      setCert(latest ? await apiGet<Certificate>(`/api/certificates/${latest.id}/`) : null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not load.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loadError) return <Message kind="error">{loadError}</Message>;
  if (!sample || !cert) {
    return (
      <div className="card">
        <div className="card-body flush"><TableSkeleton /></div>
      </div>
    );
  }

  const c = cert.content;
  const stage = cert.awaiting_stage;
  const mine = cert.can_sign && stage !== null;
  const isFinal = stage !== null && stage.order === cert.stages.length;
  const next = stage ? cert.stages.find((s) => s.order === stage.order + 1) : undefined;
  // Someone stepping in has no queue of their own to go back to.
  const back = cert.my_turn ? "/queue" : `/samples/${sample.id}`;

  // Who did (or does) each step, by name where we know it.
  const names = [
    "Front desk",
    cert.chain[0]?.name_snapshot ?? sample.analyst_name,
    ...cert.stages.map((s, i) => cert.chain[i + 1]?.name_snapshot ?? s.holder),
    "Released",
  ];
  const steps = journeySteps(sample.status, cert.stages, sample.review_stage_order, cert.prints.length > 0, names);
  const done = steps.filter((s) => s.state === "done").length;
  const currentIndex = steps.findIndex((s) => s.state === "current");
  const shown = viewing ?? steps[currentIndex]?.key ?? steps[steps.length - 1].key;
  const open = (key: string) => {
    setViewing(key);
    detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // The stage's own requirements, exactly as the server will check them on signing.
  const stageStep = stage ? exec?.steps.find((s) => s.key === stage.code) : undefined;
  const workBlocked = stageStep?.work_blockers ?? [];
  const signBlocked = [...workBlocked, ...(stageStep?.blockers ?? [])];
  const onExec = (e: Execution) => {
    setExec(e);
    void load();
  };

  const failures = c.tests.filter((t) => t.outcome === "FAIL").length;
  const headline = c.tests.find((t) => t.value !== "" && !Number.isNaN(Number(t.value)));

  const doSign = async (password: string) => {
    if (!stage) return;
    // The stage this screen showed: if someone acted meanwhile, the server
    // refuses rather than letting this signature land on a different stage.
    await apiPost(`/api/certificates/${cert.id}/sign/`, { password, stage: stage.order });
    if (isFinal) {
      toast("ok", `${c.sample_no} released`, "The certificate is approved and can be printed.");
      navigate(`/certificates/${cert.id}`);
    } else {
      toast("ok", `${c.sample_no} signed`, next ? `It is now with ${next.holder} (${next.name}).` : undefined);
      navigate(back);
    }
  };

  const doSendBack = async (comment: string) => {
    if (!stage) return;
    await apiPost(`/api/certificates/${cert.id}/return/`, { comment, stage: stage.order });
    toast("info", `${c.sample_no} sent back`, "The analyst will see your comment.");
    navigate(back);
  };

  return (
    <>
      <div className="breadcrumb">
        <Link to="/queue">My queue</Link> / {c.sample_no} · certificate v{cert.version}
      </div>

      <SampleHero
        productName={c.product_name}
        sampleNo={c.sample_no}
        batchNo={c.batch_no || c.reference || "—"}
        batchCaption={c.batch_no ? "Batch" : "Reference"}
        specVersion={c.spec_version}
        workflow={cert.workflow_name}
        pill={
          mine
            ? {
                tone: "hot",
                text: `${cert.my_turn ? "Your turn" : "As administrator"} · ${stage!.name} · review ${stage!.order} of ${cert.stages.length}`,
              }
            : cert.status === "APPROVED"
              ? { tone: "done", text: "Approved — released for print" }
              : { tone: "plain", text: stage ? `Waiting for ${stage.holder} · ${stage.name}` : cert.status.toLowerCase() }
        }
        facts={[
          headline
            ? { label: headline.name, value: `${headline.value}${headline.unit ? ` ${headline.unit}` : ""} ${headline.outcome === "PASS" ? "✓" : ""}` }
            : { label: "Results", value: `${c.tests.length}` },
          { label: "Out of spec", value: `${failures} of ${c.tests.length}`, hot: failures > 0 },
        ]}
        step={{
          current: currentIndex >= 0 ? currentIndex + 1 : steps.length,
          total: steps.length,
          done,
          label: currentIndex >= 0 ? steps[currentIndex].label : "Complete",
        }}
      />

      {execError && (
        <Message kind="error">
          Could not load this stage's checks: {execError} Do not sign until they load.
        </Message>
      )}
      {exec && <HoldBar sampleId={sample.id} exec={exec} onChange={onExec} variant="banner" />}

      <OverrideNotice rules={stageStep?.overridden ?? []} />

      <div className="journey-row">
        <section className="card" aria-label="Review journey">
          <div className="card-head">
            <h2>Review journey</h2>
            <span className="hint">{cert.chain.length} signatures, {cert.chain.length} different people — the last one releases the certificate.</span>
          </div>
          <div className="card-body">
            <Stepper status={sample.status} stages={cert.stages} reviewStage={sample.review_stage_order} mine={mine} names={names} />
          </div>
        </section>
        <CertificatePeek cert={cert} />
      </div>

      {failures > 0 && (
        <div style={{ marginBottom: 18 }}>
          <Message kind="error">
            <b>This certificate contains {failures} failing result.</b> It should not be signed.
          </Message>
        </div>
      )}

      <FailureHistory content={c} />

      <div style={{ display: "flex", flexWrap: "wrap", gap: 18, alignItems: "stretch", marginBottom: 18 }}>
        <section className="card" style={{ flex: "4 1 340px", minWidth: 0, margin: 0 }} aria-label="Journey">
          <div className="card-head"><h2>Journey</h2><span className="hint">{done} of {steps.length} steps done · open any step</span></div>
          <div className="card-body">
            <BottleProgress steps={steps} mine={mine} selected={shown} onSelect={open} />
          </div>
        </section>
        <section className="card" id="results" style={{ flex: "6 1 520px", minWidth: 0, margin: 0 }} aria-label="Results">
          <div className="card-head">
            <h2>Results against limits</h2>
            <span className="hint">Arc = allowed range · dot = result · frozen when the analyst signed</span>
          </div>
          <div className="card-body">
            <ResultGauges tests={c.tests} definitions={sample.specification.tests} />
          </div>
        </section>
      </div>

      <JourneyStepCard
        ref={detailRef}
        steps={steps}
        selected={shown}
        onSelect={setViewing}
        mine={mine}
        sample={sample}
        cert={cert}
        exec={exec}
        onExec={onExec}
        actions={exec && <HoldBar sampleId={sample.id} exec={exec} onChange={onExec} variant="button" />}
      />

      <div className="card">
        <div className="card-head">
          <h2>Signatures</h2>
          <span className="hint">{cert.chain.length} signatures, in order — each one recorded by the system</span>
        </div>
        <div className="card-body">
          <SignatureGrid chain={cert.chain} awaitingCode={stage?.code ?? null} mine={mine} />
          <div className="mono" style={{ marginTop: 14 }}>Integrity hash (SHA-256) · {cert.content_hash}</div>
        </div>
      </div>

      {mine && stage ? (
        <div className="dock" role="region" aria-label="Sign">
          <div className="dock-people">
            <SignOrbs chain={cert.chain} awaitingCode={stage.code} />
            <span className="dock-text">
              <b>{signBlocked.length > 0 ? "Sign" : "Ready to sign"} as “{fullTitle(stage.signature_title, stage.holder_title)}”{signBlocked.length > 0 ? "" : "?"}</b>
              <br />
              {signBlocked.length > 0
                ? `Not yet: ${signBlocked[0].message}${signBlocked.length > 1 ? ` (+${signBlocked.length - 1} more above)` : ""}`
                : `Your password is your signature. ${isFinal ? "Yours is the last signature — it releases the certificate." : `Next: ${next?.holder ?? "the next stage"}.`}`}{" "}
              {signBlocked.length === 0 && (
                <span className="mono">sha256 {cert.content_hash.slice(0, 8)}…{cert.content_hash.slice(-8)}</span>
              )}
            </span>
          </div>
          <button className="danger" disabled={workBlocked.length > 0} onClick={() => setModal("back")}>Send back…</button>
          <button className="primary big" disabled={signBlocked.length > 0} onClick={() => setModal("sign")}>
            ✎ {isFinal ? "Approve and release" : "Sign now"} →
          </button>
        </div>
      ) : (
        <Message kind="info">
          {stage
            ? `This certificate is waiting for “${fullTitle(stage.signature_title, stage.holder_title)}” — not for your signature.`
            : `This certificate is not waiting for a signature — it is ${cert.status.replaceAll("_", " ").toLowerCase()}.`}
        </Message>
      )}

      {modal === "sign" && stage && (
        <SignModal
          title={`Sign certificate ${c.sample_no} v${cert.version}`}
          meaning={fullTitle(stage.signature_title, stage.holder_title)}
          description={
            isFinal
              ? "Your signature releases this certificate for printing."
              : `You confirm this stage of review (“${stage.name}”) is complete.`
          }
          onConfirm={doSign}
          onClose={() => setModal(null)}
        />
      )}
      {modal === "back" && (
        <CommentModal
          title="Send back to the analyst"
          hint="This version becomes superseded and returns to the analyst. A corrected version needs every signature again — no earlier review carries over."
          label="Why is this being sent back?"
          confirmText="Send back"
          onConfirm={doSendBack}
          onClose={() => setModal(null)}
        />
      )}
    </>
  );
}
