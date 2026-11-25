import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { useAuth } from "../auth";
import CommentModal from "../components/CommentModal";
import ExecutionCard from "../components/execution/ExecutionCard";
import CloseSample from "../components/execution/CloseSample";
import HoldBar from "../components/execution/HoldBar";
import OverrideNotice from "../components/execution/OverrideNotice";
import Retests from "../components/execution/Retests";
import { BlockerList } from "../components/execution/StepPanel";
import { useExecution } from "../components/execution/useExecution";
import { EmptyState, Message, TableSkeleton } from "../components/Feedback";
import CustodyCard from "../components/lab/CustodyCard";
import RawDataFields, { BLANK_RAW, hasReadings, rawBody, RawDataView } from "../components/lab/RawData";
import type { RawDraft } from "../components/lab/RawData";
import SignModal from "../components/SignModal";
import SampleHero from "../components/SampleHero";
import BatchProgress from "../components/BatchProgress";
import CertificatePeek from "../components/CertificatePeek";
import SignatureChainCard, { SignOrbs } from "../components/SignatureChainCard";
import Stepper, { journeyNames, journeySteps } from "../components/Stepper";
import { CertStatusBadge, OutcomeBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import PrintLinks from "../components/PrintLinks";
import type {
  BatchDetail, Certificate, Execution, ResultOptions, RetestKind, RetestView, SampleDetail, TestDefinition, TestResult,
} from "../types";
import { fmtDate, fmtDateTime } from "../util";

function ResultEntryRow({
  test,
  current,
  sampleId,
  retest,
  options,
  onSaved,
  onRequestRetest,
}: {
  test: TestDefinition;
  current: TestResult | undefined;
  sampleId: number;
  /** The open retest request on this test's failed result, if any. */
  retest: RetestView | undefined;
  /** What can be named as raw data right now. */
  options: ResultOptions | null;
  onSaved: () => void;
  onRequestRetest: () => void;
}) {
  const toast = useToast();
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [raw, setRaw] = useState<RawDraft>(BLANK_RAW);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const isNumeric = test.limit_type.startsWith("NUMERIC");
  const failed = current?.outcome === "FAIL";
  const retestReady = failed && retest?.status === "AUTHORIZED";
  // An authorized retest carries its own reason; any other replacement needs one.
  const needsReason = current !== undefined && !retestReady;

  const save = async () => {
    setBusy(true);
    setError("");
    // A result on a "not more than" limit can also be "<0.05" or "ND": the server decides.
    const typed = value.trim();
    const asNumber = isNumeric && typed !== "" && !Number.isNaN(Number(typed));
    try {
      const saved = await apiPost<TestResult>(`/api/samples/${sampleId}/results/`, {
        test_definition_id: test.id,
        value_numeric: asNumber ? typed : null,
        value_text: asNumber ? "" : typed,
        supersede_reason: reason,
        ...rawBody(raw),
      });
      if (saved.outcome === "FAIL") {
        toast("error", `${test.name} is out of specification`,
          "The certificate is locked. It needs an investigation before any retest.");
      } else {
        toast("ok", retestReady ? `Retest of ${test.name} recorded` : `${test.name} recorded`,
          current ? "The previous value is kept on record beside it." : undefined);
      }
      setValue("");
      setReason("");
      setRaw(BLANK_RAW);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr>
      <td>
        <div className="cell-title">{test.name}</div>
        {test.method && <div className="cell-sub">{test.method}</div>}
      </td>
      <td>{test.limit_text}</td>
      <td>
        {current ? (
          <>
            <span className="num">
              {current.reported}
              {current.unit ? ` ${current.unit}` : ""}
            </span>{" "}
            <OutcomeBadge outcome={current.outcome} />
            <RawDataView raw={current.raw_data} />
          </>
        ) : (
          <span className="badge muted">Not entered</span>
        )}
      </td>
      <td>
        {failed && !retestReady ? (
          <div className="entry-cell">
            {retest?.status === "PENDING" ? (
              <span className="badge hot"><span className="dot" aria-hidden="true" />Retest requested — awaiting authorization</span>
            ) : (
              <>
                <button className="ghost small" onClick={onRequestRetest}>Request a retest…</button>
                <span className="cell-sub">
                  A failed result is never replaced directly. The laboratory finding comes first.
                </span>
              </>
            )}
          </div>
        ) : (
        <div className="entry-cell">
          {retestReady && <span className="badge info">Authorized retest</span>}
          {test.limit_type === "TEXT_COMPLIES" ? (
            <select
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                setError("");
              }}
              className={error ? "input-error" : ""}
              style={{ maxWidth: 190 }}
              aria-label={`Result for ${test.name}`}
            >
              <option value="">—</option>
              <option value={test.text_expected}>{test.text_expected}</option>
              <option value="Does not comply">Does not comply</option>
            </select>
          ) : (
            <input
              className={`short ${error ? "input-error" : ""}`}
              type="text"
              placeholder={
                test.limit_type === "NUMERIC_MAX"
                  ? `number, <0.05 or ND${test.unit ? ` (${test.unit})` : ""}`
                  : isNumeric
                    ? `number${test.unit ? ` (${test.unit})` : ""}`
                    : test.unit || "result"
              }
              inputMode={isNumeric ? "decimal" : undefined}
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                setError("");
              }}
              aria-label={`Result for ${test.name}`}
              aria-invalid={!!error}
            />
          )}
          {needsReason && (
            <input
              placeholder="Reason for replacing the existing result (required)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              style={{ minWidth: 240, flex: 1 }}
            />
          )}
          <button
            className={needsReason ? "danger small" : "ghost small"}
            disabled={busy || (!value && !hasReadings(raw)) || (needsReason && !reason.trim())}
            onClick={() => void save()}
          >
            {busy ? "Saving…" : retestReady ? "Enter retest" : needsReason ? "Replace" : "Save"}
          </button>
          <RawDataFields raw={raw} options={options} numeric={test.limit_type !== "TEXT_COMPLIES"} onChange={setRaw} />
        </div>
        )}
        {error && (
          <div className="field-error" style={{ marginTop: 7 }} role="alert">
            <span aria-hidden="true">▲</span> {error}
          </div>
        )}
      </td>
    </tr>
  );
}

export default function SampleDetailPage() {
  const { id } = useParams();
  const { user, can } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [sample, setSample] = useState<SampleDetail | null>(null);
  const [showSign, setShowSign] = useState(false);
  const [retestFor, setRetestFor] = useState<TestDefinition | null>(null);
  const [retestKind, setRetestKind] = useState<RetestKind>("RETEST");
  const [loadError, setLoadError] = useState("");
  const [rawOptions, setRawOptions] = useState<ResultOptions | null>(null);
  const { exec, setExec, error: execError, reload: reloadExec } = useExecution(id);
  // The certificate now in force (in review, or released): who has signed it and who is next.
  const [liveCert, setLiveCert] = useState<Certificate | null>(null);
  const liveId = sample?.certificates
    .filter((c) => c.status === "IN_REVIEW" || c.status === "APPROVED")
    .sort((a, b) => b.version - a.version)[0]?.id ?? null;
  const liveKey = `${sample?.status}-${sample?.review_stage_order}`;
  // The batch it belongs to, for the QC stages it is going through.
  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const batchId = sample?.batch_id ?? null;
  useEffect(() => {
    if (batchId === null) {
      setBatch(null);
      return undefined;
    }
    let live = true;
    apiGet<BatchDetail>(`/api/batches/${batchId}/`)
      .then((b) => live && setBatch(b))
      .catch(() => live && setBatch(null));
    return () => {
      live = false;
    };
  }, [batchId, liveKey]);
  useEffect(() => {
    if (liveId === null) {
      setLiveCert(null);
      return undefined;
    }
    let live = true;
    apiGet<Certificate>(`/api/certificates/${liveId}/`)
      .then((c) => live && setLiveCert(c))
      .catch(() => live && setLiveCert(null));
    return () => {
      live = false;
    };
  }, [liveId, liveKey]);

  const load = useCallback(async () => {
    try {
      setSample(await apiGet<SampleDetail>(`/api/samples/${id}/`));
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not load sample.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  // Offered on the entry rows. Without it the rows still work: the raw data is optional.
  const entering = can("result.enter");
  useEffect(() => {
    if (entering) apiGet<ResultOptions>("/api/lab/result-options/").then(setRawOptions).catch(() => setRawOptions(null));
  }, [entering]);

  // A change inside a step (hold, handover…) can change what the sample shows too.
  const onExec = (e: Execution) => {
    setExec(e);
    void load();
  };

  if (loadError) return <Message kind="error">{loadError}</Message>;
  if (!sample) {
    return (
      <div className="card">
        <div className="card-body flush"><TableSkeleton /></div>
      </div>
    );
  }

  const receiptStep = exec?.steps.find((s) => s.kind === "receipt");
  const receiptOpen = receiptStep?.is_current ?? false;
  const isAnalyst = sample.assigned_analyst_id === user?.id;
  const canEnter =
    can("result.enter") &&
    // An administrator can stand in for the analyst; the server flags it in the activity log.
    (isAnalyst || can("admin.override")) &&
    (sample.status === "RECEIVED" || sample.status === "IN_TESTING") &&
    !receiptOpen &&
    // On hold, or handed over and not yet accepted: the server would refuse anyway.
    exec?.steps.find((s) => s.key === "TESTING")?.can.work !== false;
  const failedNow = sample.results.filter((r) => !r.is_superseded && r.outcome === "FAIL");
  const currentByTest = new Map(
    sample.results.filter((r) => !r.is_superseded).map((r) => [r.test_definition_id, r]),
  );
  const tests = sample.specification.tests;
  const entered = tests.filter((t) => currentByTest.has(t.id)).length;
  const allEntered = entered === tests.length;
  const hasFail = sample.results.some((r) => !r.is_superseded && r.outcome === "FAIL");
  const history = sample.results.filter((r) => r.is_superseded);
  const approvedCert = sample.certificates.find((c) => c.status === "APPROVED");
  const failCount = sample.results.filter((r) => !r.is_superseded && r.outcome === "FAIL").length;
  const steps = journeySteps(sample.status, sample.workflow.stages, sample.review_stage_order, false);
  const currentIndex = steps.findIndex((s) => s.state === "current");
  const stage = sample.workflow.stages.find((s) => s.order === sample.review_stage_order);
  const myTurn = (canEnter && isAnalyst) || sample.my_turn;
  const pill: { tone: "hot" | "done" | "plain"; text: string } = receiptOpen
    ? receiptStep?.can.work
      ? { tone: "hot", text: "Your turn · receipt checks" }
      : { tone: "plain", text: "Waiting for receipt checks" }
    : canEnter
    ? {
        tone: "hot",
        text: `${isAnalyst ? "Your turn" : "As administrator"} · ${allEntered ? "sign as “Analysed by”" : "enter the results"}`,
      }
    : sample.can_sign && stage
      ? { tone: "hot", text: `${sample.my_turn ? "Your turn" : "As administrator"} · ${stage.name}` }
      : sample.status === "APPROVED"
        ? { tone: "done", text: "Approved — certificate released" }
        : { tone: "plain", text: sample.status_label };

  const testing = exec?.steps.find((s) => s.key === "TESTING");
  // The server's own list of what still stands in the way — the same check it makes on signing.
  const signBlockers = testing && testing.is_current ? testing.blockers : [];
  const openRetest = (testId: number) =>
    exec?.retests.find((r) => r.test_definition_id === testId && (r.status === "PENDING" || r.status === "AUTHORIZED"));

  const signAnalyst = async (password: string) => {
    const cert = await apiPost<Certificate>(`/api/samples/${sample.id}/sign-analyst/`, { password });
    const first = cert.stages[0];
    toast("ok", `Certificate v${cert.version} signed`, first ? `It is now with ${first.holder} (${first.name}).` : undefined);
    navigate(`/certificates/${cert.id}`);
  };

  return (
    <>
      <div className="breadcrumb">
        <Link to={can("sample.view.all") ? "/samples" : "/worklist"}>Samples</Link> / {sample.sample_no}
      </div>
      <SampleHero
        productName={sample.product_name}
        sampleNo={sample.sample_no}
        batchNo={sample.batch_label}
        batchCaption={sample.batch_id ? "Batch" : "Reference"}
        specVersion={sample.specification.version}
        workflow={`${sample.workflow.name} v${sample.workflow.version}`}
        pill={pill}
        facts={[
          { label: "Results entered", value: `${entered} of ${tests.length}` },
          { label: "Out of spec", value: `${failCount}`, hot: failCount > 0 && sample.status !== "APPROVED" },
        ]}
        step={{
          current: currentIndex >= 0 ? currentIndex + 1 : steps.length,
          total: steps.length,
          done: steps.filter((s) => s.state === "done").length,
          label: currentIndex >= 0 ? steps[currentIndex].label : "Complete",
        }}
      />

      {execError && (
        <Message kind="error">
          Could not load this sample's steps and checks: {execError} What is shown here may not be complete.
        </Message>
      )}
      {exec && <HoldBar sampleId={sample.id} exec={exec} onChange={onExec} variant="banner" />}

      {sample.closed_at && (
        <Message kind={sample.status === "REJECTED" ? "error" : "info"}>
          <b>{sample.status === "REJECTED" ? "Rejected" : "Cancelled"} by {sample.closed_by_name}.</b> {sample.closed_reason}
        </Message>
      )}
      {(failedNow.length > 0 || sample.investigations.length > 0) && (
        <section className="card" aria-label="Failures and investigations">
          <div className="card-head"><h2>Failures and investigations</h2></div>
          <div className="card-body stack">
            {failedNow.map((r) => (
              <div key={r.id} className="actions-bar">
                <span><b>{r.test_name}</b> failed at <span className="num">{r.reported}{r.unit ? ` ${r.unit}` : ""}</span>.</span>
                <div className="spacer" />
                {can("investigation.manage") && !sample.investigations.some(
                  (i) => i.test_name === r.test_name && i.status !== "CLOSED",
                ) && <Link to={`/investigations/new?result=${r.id}`}>Open investigation…</Link>}
              </div>
            ))}
            {sample.investigations.map((i) => (
              <div key={i.id} className="actions-bar">
                <Link to={`/investigations/${i.id}`}>{i.reference}</Link>
                <span className="hint">{i.kind}{i.test_name ? ` · ${i.test_name}` : ""}</span>
                <span className="badge muted">{i.status_label}</span>
                {i.conclusion && <span className="hint">{i.conclusion}</span>}
              </div>
            ))}
          </div>
        </section>
      )}
      {exec && (exec.can_reject || exec.can_cancel) && (
        <div className="actions-bar" style={{ justifyContent: "flex-end", marginBottom: 12 }}>
          <CloseSample sampleId={sample.id} exec={exec} onChange={() => void load()} />
        </div>
      )}

      <OverrideNotice rules={exec?.steps.find((s) => s.is_current)?.overridden ?? []} />

      {receiptOpen && (
        <div style={{ marginBottom: 16 }}>
          <Message kind="info">
            <b>Receipt checks are open.</b>{" "}
            {receiptStep?.can.work
              ? "Complete them under Step work below — testing cannot start until you do."
              : "Testing opens as soon as the front desk completes them."}
          </Message>
        </div>
      )}

      <div className="journey-row">
        <section className="card" aria-label="Where this sample is">
          <div className="card-head">
            <h2>{liveCert ? "Review journey" : "Where this sample is"}</h2>
            <span className="hint">
              {liveCert
                ? `${liveCert.chain.length} signatures, ${liveCert.chain.length} different people — the last one releases the certificate.`
                : `Step ${currentIndex >= 0 ? currentIndex + 1 : steps.length} of ${steps.length}${currentIndex >= 0 ? ` · ${steps[currentIndex].label}` : ""}`}
            </span>
          </div>
          <div className="card-body">
            <Stepper
              status={sample.status}
              stages={sample.workflow.stages}
              reviewStage={sample.review_stage_order}
              mine={myTurn}
              names={journeyNames(exec, sample.workflow.stages, sample.analyst_name)}
            />
            {sample.can_sign && (
              <div className="actions-bar" style={{ marginTop: 16, justifyContent: "center" }}>
                <button className="primary" onClick={() => navigate(`/samples/${sample.id}/review`)}>
                  ✎ Open the review{sample.my_turn ? " — it is waiting for you" : ""} →
                </button>
              </div>
            )}
          </div>
        </section>
        {liveCert && <CertificatePeek cert={liveCert} />}
      </div>

      {liveCert && <SignatureChainCard cert={liveCert} />}

      {batch && <BatchProgress batch={batch} forStageId={sample.qc_stage_id} />}

      <div className="card">
        <div className="card-head">
          <h2>Sample details</h2>
          <div className="spacer" />
          <div className="actions-bar">
            <PrintLinks items={[
              { label: "Label", icon: "label", href: `/api/samples/${sample.id}/label/`, hint: "The sample label, to stick on the container." },
              { label: "Sample record", icon: "record", href: `/api/samples/${sample.id}/record/`,
                hint: "The whole sample record: details, results, review and signatures." },
            ]} />
          </div>
        </div>
        <div className="card-body">
          <div className="kv">
            <div><div className="k">Section</div><div className="v">{sample.section_code}</div></div>
            {sample.batch_id ? (
              <div>
                <div className="k">Batch</div>
                <div className="v"><Link to={`/batches/${sample.batch_id}`}>{sample.batch_no}</Link></div>
                <div className="cell-sub mono">{sample.batch_internal_id}</div>
              </div>
            ) : (
              <div><div className="k">Reference</div><div className="v">{sample.reference}</div></div>
            )}
            {sample.qc_stage_name && (
              <div><div className="k">QC stage</div><div className="v">{sample.qc_stage_name}</div></div>
            )}
            {sample.manufacturing_site && (
              <div><div className="k">Manufacturing site</div><div className="v">{sample.manufacturing_site}</div></div>
            )}
            <div><div className="k">Quantity</div><div className="v">{sample.quantity}</div></div>
            <div><div className="k">Received from</div><div className="v">{sample.received_from}</div></div>
            <div><div className="k">Received at</div><div className="v">{fmtDateTime(sample.received_at)}</div></div>
            <div><div className="k">Due date</div><div className="v">{fmtDate(sample.due_date)}</div></div>
            <div><div className="k">Analyst</div><div className="v">{sample.analyst_name}</div></div>
            <div><div className="k">Registered by</div><div className="v">{sample.registered_by_name}</div></div>
            <div>
              <div className="k">Specification</div>
              <div className="v">
                {sample.specification.stage_name
                  ? `${sample.specification.stage_name} tests, version ${sample.specification.version}`
                  : `Version ${sample.specification.version}`}
              </div>
            </div>
            <div>
              <div className="k">Review workflow</div>
              <div className="v">{sample.workflow.name} v{sample.workflow.version}</div>
            </div>
            {sample.manufacturing_date && (
              <div>
                <div className="k">Date of manufacture</div>
                <div className="v">{fmtDate(sample.manufacturing_date)}</div>
              </div>
            )}
            {sample.expiry_date && (
              <div>
                <div className="k">Expiry / retest</div>
                <div className="v">{fmtDate(sample.expiry_date)}</div>
              </div>
            )}
            {sample.past_expiry_reason && (
              <div>
                <div className="k">Tested past expiry</div>
                <div className="v">{sample.past_expiry_reason}</div>
              </div>
            )}
            {sample.storage_condition && (
              <div style={{ gridColumn: "span 2" }}>
                <div className="k">Storage condition</div>
                <div className="v">{sample.storage_condition}</div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Tests and results</h2>
          <span className="hint">{entered} of {tests.length} entered</span>
        </div>
        <div className="card-body flush">
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th style={{ width: "24%" }}>Test</th>
                  <th style={{ width: "20%" }}>Allowed limit</th>
                  <th style={{ width: canEnter ? "18%" : "28%" }}>Result</th>
                  <th>{canEnter ? "Enter / correct" : "Entered by"}</th>
                </tr>
              </thead>
              <tbody>
                {tests.map((t) => {
                  const current = currentByTest.get(t.id);
                  if (canEnter) {
                    return (
                      <ResultEntryRow
                        key={t.id}
                        test={t}
                        current={current}
                        sampleId={sample.id}
                        retest={openRetest(t.id)}
                        options={rawOptions}
                        onSaved={() => {
                          void load();
                          void reloadExec();
                        }}
                        onRequestRetest={() => setRetestFor(t)}
                      />
                    );
                  }
                  return (
                    <tr key={t.id}>
                      <td>
                        <div className="cell-title">{t.name}</div>
                        {t.method && <div className="cell-sub">{t.method}</div>}
                      </td>
                      <td>{t.limit_text}</td>
                      <td>
                        {current ? (
                          <>
                            <span className="num">
                              {current.reported}
                              {current.unit ? ` ${current.unit}` : ""}
                            </span>{" "}
                            <OutcomeBadge outcome={current.outcome} />
                            <RawDataView raw={current.raw_data} />
                          </>
                        ) : (
                          <span className="badge muted">Not entered</span>
                        )}
                      </td>
                      <td>
                        {current ? (
                          <>
                            <div>{current.entered_by_name}</div>
                            <div className="cell-sub">{fmtDateTime(current.entered_at)}</div>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {canEnter && (
            <div className="card-body" style={{ borderTop: "1px solid var(--line)" }}>
              {signBlockers.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <BlockerList blockers={signBlockers} />
                </div>
              )}
              <div className="actions-bar">
                <span style={{ fontSize: 13, color: "var(--ink-3)" }}>
                  {signBlockers.length > 0
                    ? `${signBlockers.length} thing${signBlockers.length > 1 ? "s" : ""} to finish before signing.`
                    : "Everything is in. Signing freezes the certificate."}
                </span>
                <div className="spacer" />
                <button
                  className="primary"
                  disabled={!allEntered || hasFail || signBlockers.length > 0}
                  onClick={() => setShowSign(true)}
                >
                  ✎ Sign as “Analysed by”
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {exec && <Retests exec={exec} analystId={sample.assigned_analyst_id} onChange={onExec} />}

      {exec && <ExecutionCard sampleId={sample.id} exec={exec} onChange={onExec} />}

      {history.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h2>Replaced results</h2>
            <span className="hint">Kept forever — nothing is ever deleted</span>
          </div>
          <div className="card-body flush">
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr><th>Test</th><th>Old value</th><th>Replaced by</th><th>When</th><th>Why</th><th>Raw data</th></tr>
                </thead>
                <tbody>
                  {history.map((r) => (
                    <tr key={r.id} className="superseded">
                      <td>{r.test_name}</td>
                      <td><span className="struck">{r.reported}</span></td>
                      <td>{r.superseded_by_name}</td>
                      <td>{r.superseded_at ? fmtDateTime(r.superseded_at) : ""}</td>
                      <td>{r.supersede_reason}</td>
                      <td>{r.raw_data ? <RawDataView raw={r.raw_data} /> : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      <CustodyCard sampleId={sample.id} />

      <div className="card">
        <div className="card-head">
          <h2>Certificates</h2>
          {approvedCert && <span className="hint">v{approvedCert.version} is the released version</span>}
        </div>
        <div className="card-body flush">
          {sample.certificates.length === 0 ? (
            <EmptyState
              title="No certificate yet"
              sub="One is created the moment the analyst signs."
            />
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr><th>Version</th><th>Status</th><th>Created</th><th /></tr>
                </thead>
                <tbody>
                  {sample.certificates.map((c) => (
                    <tr key={c.id} className="clickable" onClick={() => navigate(`/certificates/${c.id}`)}>
                      <td className="num">v{c.version}</td>
                      <td><CertStatusBadge status={c.status} /></td>
                      <td>{fmtDateTime(c.created_at)}</td>
                      <td><Link to={`/certificates/${c.id}`} className="btn-link">Open →</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>History</h2></div>
        <div className="card-body">
          <ul className="timeline">
            {sample.events.map((e) => (
              <li key={e.id}>
                <span className="when">{fmtDateTime(e.at)}</span>
                <span>
                  <b>{e.actor_name}</b>
                  {e.from_status !== e.to_status && (
                    <> — {e.from_status.replaceAll("_", " ").toLowerCase()} → {e.to_status.replaceAll("_", " ").toLowerCase()}</>
                  )}
                  {e.comment && <span className="comment">“{e.comment}”</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {liveCert && liveCert.status === "IN_REVIEW" && liveCert.can_sign && liveCert.awaiting_stage && (
        <div className="dock" role="region" aria-label="Your signature is waiting">
          <div className="dock-people">
            <SignOrbs chain={liveCert.chain} awaitingCode={liveCert.awaiting_stage.code} />
            <span className="dock-text">
              <b>
                {liveCert.my_turn ? "Your turn" : "As administrator"}: sign as “{liveCert.awaiting_stage.signature_title}
                {liveCert.awaiting_stage.holder_title ? ` (${liveCert.awaiting_stage.holder_title})` : ""}”
              </b>
              <br />
              {liveCert.awaiting_stage.order === liveCert.stages.length
                ? "Yours is the last signature — it releases the certificate."
                : `Next: ${liveCert.stages.find((s) => s.order === liveCert.awaiting_stage!.order + 1)?.holder ?? "the next stage"}.`}
            </span>
          </div>
          <button className="primary big" onClick={() => navigate(`/samples/${sample.id}/review`)}>✎ Review and sign →</button>
        </div>
      )}

      {retestFor && (
        <CommentModal
          title={`Request a retest of ${retestFor.name}`}
          hint="Someone independent with the permission to authorize retests will read your reason. The failed result stays on record whatever they decide."
          label="Why is a retest justified?"
          confirmText="Request retest"
          tone="primary"
          placeholder="e.g. Dilution error found on the worksheet — the standard was prepared at half strength."
          onConfirm={async (reason) => {
            setExec(await apiPost<Execution>(`/api/samples/${sample.id}/retests/`, {
              test_definition_id: retestFor.id, reason, kind: retestKind,
            }));
            setRetestFor(null);
            setRetestKind("RETEST");
            toast("info", "Retest requested", "It is waiting for authorization.");
          }}
          onClose={() => setRetestFor(null)}
        >
          <label className="field">
            Type
            <select value={retestKind} onChange={(e) => setRetestKind(e.target.value as RetestKind)}>
              <option value="RETEST">Retest</option>
              <option value="REPEAT">Repeat analysis</option>
              <option value="RESAMPLE">Resample</option>
            </select>
          </label>
        </CommentModal>
      )}

      {showSign && (
        <SignModal
          title={`Sign certificate for ${sample.sample_no}`}
          meaning="Analysed by"
          description="The certificate will be built from these results and frozen exactly as shown."
          onConfirm={signAnalyst}
          onClose={() => setShowSign(false)}
        />
      )}
    </>
  );
}
