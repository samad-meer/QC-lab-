import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { useAuth } from "../auth";
import CommentModal from "../components/CommentModal";
import { EmptyState, Message, TableSkeleton } from "../components/Feedback";
import SampleHero from "../components/SampleHero";
import SignatureGrid from "../components/SignatureGrid";
import Stepper, { journeySteps } from "../components/Stepper";
import { OutcomeBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import type { Certificate } from "../types";
import { fmtDate, fmtDateTime } from "../util";

export default function CertificatePage() {
  const { id } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [cert, setCert] = useState<Certificate | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const [password, setPassword] = useState("");

  const load = useCallback(async () => {
    try {
      setCert(await apiGet<Certificate>(`/api/certificates/${id}/`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load certificate.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !cert) return <Message kind="error">{error}</Message>;
  if (!cert) {
    return (
      <div className="card">
        <div className="card-body flush"><TableSkeleton /></div>
      </div>
    );
  }
  const c = cert.content;

  const copyUrl = (copy: number) => `/api/certificates/${cert.id}/print-view/?copy=${copy}`;

  // The window opens inside the click, before anything is recorded: a browser
  // blocks one opened later, and a blocked window must not cost a numbered copy.
  const openPrintWindow = (url = "") => {
    const win = window.open(url, "_blank");
    if (!win) {
      const msg = "Your browser blocked the print window, so nothing was recorded. Allow pop-ups for this site and try again.";
      setError(msg);
      toast("error", "Print window blocked", msg);
    }
    return win;
  };

  const doPrint = async () => {
    const win = openPrintWindow();
    if (!win) return;
    win.document.title = "Preparing the certificate…";
    win.document.body.textContent = "Preparing the certificate…";
    setBusy(true);
    setError("");
    try {
      const { copy_number } = await apiPost<{ copy_number: number }>(
        `/api/certificates/${cert.id}/print/`,
      );
      win.location.href = copyUrl(copy_number);
      toast(
        "ok",
        copy_number === 1 ? "Original printed" : `Duplicate copy ${copy_number} printed`,
        "Recorded against your name.",
      );
      await load();
    } catch (err) {
      win.close();
      const msg = err instanceof Error ? err.message : "Print refused.";
      setError(msg);
      toast("error", "Print refused", msg);
    } finally {
      setBusy(false);
    }
  };

  // A copy already recorded whose window closed before it loaded.
  const openCopy = (copy: number) => {
    setError("");
    if (openPrintWindow(copyUrl(copy))) void load();
  };

  const sampleStatus = cert.status === "APPROVED" ? "APPROVED" : "IN_REVIEW";
  const printed = cert.prints.length > 0;
  const steps = journeySteps(sampleStatus, cert.stages, cert.awaiting_stage?.order ?? null, printed);
  const currentIndex = steps.findIndex((s) => s.state === "current");
  const pill: { tone: "hot" | "done" | "plain"; text: string } =
    cert.status === "APPROVED"
      ? { tone: "done", text: printed ? "Approved · printed" : "Approved — ready to print" }
      : cert.status === "SUPERSEDED"
        ? { tone: "plain", text: "Superseded version" }
        : cert.can_sign && cert.awaiting_stage
          ? { tone: "hot", text: `${cert.my_turn ? "Your turn" : "As administrator"} · ${cert.awaiting_stage.name}` }
          : { tone: "plain", text: cert.awaiting_stage ? `Waiting for ${cert.awaiting_stage.holder}` : "In review" };

  return (
    <>
      <div className="breadcrumb">
        <Link to={`/samples/${cert.sample_id}`}>{c.sample_no}</Link> / Certificate v{cert.version}
      </div>
      <SampleHero
        productName={c.product_name}
        sampleNo={c.sample_no}
        batchNo={c.batch_no || c.reference || "—"}
        batchCaption={c.batch_no ? "Batch" : "Reference"}
        specVersion={c.spec_version}
        workflow={cert.workflow_name}
        pill={pill}
        facts={[
          { label: `Certificate v${cert.version}`, value: c.overall, hot: c.overall !== "COMPLIES" },
          { label: "Copies printed", value: `${cert.prints.length}` },
        ]}
        step={{
          current: currentIndex >= 0 ? currentIndex + 1 : steps.length,
          total: steps.length,
          done: steps.filter((s) => s.state === "done").length,
          label: currentIndex >= 0 ? steps[currentIndex].label : "Complete",
        }}
      />

      {cert.status === "SUPERSEDED" && (
        <div style={{ marginBottom: 16 }}>
          <Message kind="warn">
            <b>This version was superseded.</b>
            {cert.superseded_reason && <> “{cert.superseded_reason}”</>} Its signatures stay on
            record; a newer version carries the valid ones.
          </Message>
        </div>
      )}

      {cert.status !== "SUPERSEDED" && (
        <div className="card">
          <div className="card-body">
            <Stepper
              status={sampleStatus}
              stages={cert.stages}
              reviewStage={cert.awaiting_stage?.order ?? null}
              printed={printed}
              mine={cert.my_turn}
            />
            {cert.can_sign && (
              <div className="actions-bar" style={{ marginTop: 16, justifyContent: "center" }}>
                <button className="primary" onClick={() => navigate(`/samples/${cert.sample_id}/review`)}>
                  ✎ Open the review →
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-head"><h2>Certificate details</h2></div>
        <div className="card-body">
          <div className="kv">
            <div><div className="k">Product</div><div className="v">{c.product_name}</div></div>
            <div><div className="k">Product code</div><div className="v">{c.product_code}</div></div>
            {(c.dosage_form || c.strength) && (
              <div>
                <div className="k">Dosage form · strength</div>
                <div className="v">{[c.dosage_form, c.strength].filter(Boolean).join(" · ")}</div>
              </div>
            )}
            <div>
              <div className="k">{c.batch_no ? "Batch / Lot" : "Reference"}</div>
              <div className="v">{c.batch_no || c.reference}</div>
            </div>
            {c.internal_batch_id && (
              <div><div className="k">Internal batch ID</div><div className="v mono">{c.internal_batch_id}</div></div>
            )}
            {c.manufacturing_site && (
              <div><div className="k">Manufacturing site</div><div className="v">{c.manufacturing_site}</div></div>
            )}
            <div><div className="k">Section</div><div className="v">{c.section}</div></div>
            <div><div className="k">Quantity</div><div className="v">{c.quantity}</div></div>
            <div><div className="k">Received from</div><div className="v">{c.received_from}</div></div>
            {c.qc_stage && (
              <div><div className="k">QC stage</div><div className="v">{c.qc_stage}</div></div>
            )}
            <div>
              <div className="k">Specification</div>
              <div className="v">{c.spec_of_stage ? `${c.spec_of_stage} tests, version ${c.spec_version}` : `Version ${c.spec_version}`}</div>
            </div>
            <div><div className="k">Conclusion</div><div className="v">{c.overall}</div></div>
            <div><div className="k">Review workflow</div><div className="v">{cert.workflow_name}</div></div>
            {c.manufacturing_date && (
              <div>
                <div className="k">Date of manufacture</div>
                <div className="v">{fmtDate(c.manufacturing_date)}</div>
              </div>
            )}
            {c.expiry_date && (
              <div>
                <div className="k">Expiry / retest</div>
                <div className="v">{fmtDate(c.expiry_date)}</div>
              </div>
            )}
            {c.storage_condition && (
              <div style={{ gridColumn: "span 2" }}>
                <div className="k">Storage condition</div>
                <div className="v">{c.storage_condition}</div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>Results</h2></div>
        <div className="card-body flush">
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr><th>#</th><th>Test</th><th>Method</th><th>Limit</th><th>Result</th><th>Outcome</th></tr>
              </thead>
              <tbody>
                {c.tests.map((t, i) => (
                  <tr key={i}>
                    <td>{i + 1}</td>
                    <td className="cell-title">{t.name}</td>
                    <td>{t.method}</td>
                    <td>{t.limit_text}</td>
                    <td className="num">
                      {t.value}{t.unit ? ` ${t.unit}` : ""}
                      {t.retested && <span className="tag soft" style={{ marginLeft: 6 }} title="An authorized retest — see below">R</span>}
                    </td>
                    <td><OutcomeBadge outcome={t.outcome} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {c.retests && c.retests.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h2>Retests</h2>
            <span className="hint">Printed on this certificate</span>
          </div>
          <div className="card-body flush">
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr><th>Test</th><th>Original result</th><th>Reason for retest</th><th>Authorized by</th><th>Retest result</th></tr>
                </thead>
                <tbody>
                  {c.retests.map((r, i) => (
                    <tr key={i}>
                      <td className="cell-title">{r.test}</td>
                      <td className="num">
                        {r.original_value}{r.unit ? ` ${r.unit}` : ""}
                        <div className="cell-sub">{fmtDateTime(r.original_entered_at)}</div>
                      </td>
                      <td>{r.reason}<div className="cell-sub">Requested by {r.requested_by}</div></td>
                      <td>{r.authorized_by}<div className="cell-sub">{fmtDateTime(r.authorized_at)}</div></td>
                      <td className="num">
                        {r.retest_value}{r.unit ? ` ${r.unit}` : ""} <OutcomeBadge outcome={r.retest_outcome} />
                        <div className="cell-sub">{fmtDateTime(r.retest_entered_at)}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <h2>Signatures</h2>
          <span className="hint">
            {cert.chain.length} signatures, in order — each one recorded by the system
          </span>
        </div>
        <div className="card-body">
          <SignatureGrid chain={cert.chain} awaitingCode={cert.awaiting_stage?.code ?? null} mine={cert.my_turn} />
          <div className="mono" style={{ marginTop: 14 }}>
            Integrity hash (SHA-256) · {cert.content_hash}
          </div>
          <div style={{ marginTop: 6, fontSize: 13 }}>
            <a href={`/verify/${cert.verification_uuid}/`} target="_blank" rel="noreferrer">
              Open the public verification page ↗
            </a>{" "}
            <span style={{ color: "var(--ink-3)" }}>— what the QR code on the printed copy shows</span>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Printing</h2>
          {cert.prints.length > 0 && (
            <span className="hint">
              {cert.prints.length} cop{cert.prints.length === 1 ? "y" : "ies"} issued
            </span>
          )}
        </div>
        <div className="card-body">
          {cert.status === "WITHDRAWN" ? (
            <Message kind="error">
              <b>Withdrawn by {cert.withdrawn_by_name}.</b> {cert.withdrawn_reason} This certificate cannot be
              printed, and its verification page says it was withdrawn.
            </Message>
          ) : cert.status === "APPROVED" ? (
            <>
              <div className="actions-bar" style={{ marginBottom: cert.prints.length ? 16 : 0 }}>
                <button className="primary" disabled={busy || !can("cert.print")} onClick={() => void doPrint()}>
                  {busy
                    ? "Recording…"
                    : cert.prints.length === 0
                      ? "Print original"
                      : `Print duplicate copy ${cert.prints.length + 1}`}
                </button>
                <span style={{ fontSize: 13, color: "var(--ink-3)" }}>
                  Every print is recorded — who, when, and which copy number.
                </span>
                <div className="spacer" />
                {cert.can_withdraw && (
                  <button className="danger small" onClick={() => setWithdrawing(true)}>Withdraw…</button>
                )}
              </div>
              {error && <Message kind="error">{error}</Message>}
              {cert.prints.length > 0 && (
                <div className="table-wrap">
                  <table className="grid">
                    <thead>
                      <tr><th>Copy</th><th>Printed by</th><th>When</th><th /></tr>
                    </thead>
                    <tbody>
                      {cert.prints.map((p) => (
                        <tr key={p.copy_number}>
                          <td>
                            {p.copy_number === 1 ? (
                              <span className="badge info">1 · Original</span>
                            ) : (
                              <span className="badge muted">{p.copy_number} · Duplicate</span>
                            )}
                          </td>
                          <td>{p.printed_by_name}</td>
                          <td>{fmtDateTime(p.printed_at)}</td>
                          <td>
                            {p.can_open && (
                              <button className="ghost small" onClick={() => openCopy(p.copy_number)}>
                                Never opened — open it
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : cert.status === "SUPERSEDED" ? (
            <EmptyState
              title="This version can never be printed"
              sub="It was superseded before release."
            />
          ) : (
            <Message kind="info">
              Until all {cert.chain.length} signatures are on it, the print button does nothing.
              {cert.awaiting_stage
                ? ` It is waiting for “${cert.awaiting_stage.signature_title}” (${cert.awaiting_stage.holder}).`
                : ""}
            </Message>
          )}
        </div>
      </div>
      {withdrawing && (
        <CommentModal
          title="Withdraw this certificate"
          hint="Its content stays as it was signed. It can no longer be printed, and scanning its QR code says it was withdrawn."
          label="Why is it being withdrawn?"
          confirmText="Withdraw certificate"
          onConfirm={async (reason) => {
            setCert(await apiPost<Certificate>(`/api/certificates/${cert.id}/withdraw/`, { password, reason }));
            setWithdrawing(false);
            setPassword("");
          }}
          onClose={() => { setWithdrawing(false); setPassword(""); }}
        >
          <label className="field">
            Your password <span className="note">this is a signature</span>
            <input type="password" required autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </label>
        </CommentModal>
      )}
    </>
  );
}
