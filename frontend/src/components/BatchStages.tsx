import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { apiPost } from "../api";
import { useAuth } from "../auth";
import { modeShown } from "../stageKinds";
import type { BatchDetail, BatchStagesView, StageKind } from "../types";
import Avatar from "./Avatar";
import CommentModal from "./CommentModal";
import { Message } from "./Feedback";
import LineIcon, { type IconName } from "./LineIcon";
import Stamp from "./Stamp";
import StageRecord from "./StageRecord";
import { useToast } from "./Toast";

type StageRow = BatchStagesView["stages"][number];

const TONES: Record<string, string> = {
  PASSED: "pass", FAILED: "fail", IN_PROGRESS: "warn", NOT_STARTED: "muted", NOT_APPLICABLE: "muted",
};

function PasswordField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <label className="field">
      Your password <span className="note">this is a signature</span>
      <input type="password" required autoComplete="current-password" value={value}
        onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

/** The front desk, opened on this batch and stage, so nothing is typed twice. */
function registerLink(batch: BatchDetail, stage: StageRow): string {
  const q = new URLSearchParams({
    section: batch.product.section, product: String(batch.product.id),
    batch: batch.official_batch_no, stage: String(stage.id),
  });
  return `/frontdesk?${q.toString()}`;
}

/** Every sign-off column of a batch-record stage: the stage's own, or each step's. */
function columnsOf(s: StageRow) {
  return s.record ? [...s.record.signoffs, ...s.record.steps.flatMap((st) => st.signoffs)] : [];
}

/** Why this stage is waiting on the person looking, or "" when it is not. */
function forYou(s: StageRow, view: BatchStagesView, userId: number | undefined): string {
  if (s.status === "PASSED" || s.status === "FAILED" || s.status === "NOT_APPLICABLE") return "";
  if (s.assignment?.holder && s.assignment.holder.id === userId) return "Assigned to you";
  if (columnsOf(s).some((c) => !c.signature && !c.blocked)) return "Your signature";
  if (s.record?.can_fill && !s.record.locked) return "For you to fill in";
  const waiting = s.waiting_for.length > 0 && s.status === "NOT_STARTED";
  if (waiting) return "";
  if (s.kind === "RECORDED" && !s.record && view.can_record) return "For you to record";
  if (s.kind === "TESTED" && view.can_register && s.samples.length === 0 && s.hidden_samples === 0) {
    return "Needs a sample";
  }
  return "";
}

/** How a stage is done, as an icon and a word: on the batch record, in the lab, or recorded by QA. */
function kindOf(s: StageRow): { icon: IconName; label: string } {
  if (s.record) return { icon: "record", label: "Batch record" };
  if (s.kind === "TESTED") return { icon: "flask", label: s.kind_label };
  return { icon: "sign", label: s.kind_label };
}

function Owner({ icon, avatar, title, sub, muted }: {
  icon?: IconName; avatar?: string; title: string; sub: string; muted?: boolean;
}) {
  return (
    <>
      {avatar ? <Avatar name={avatar} size={26} />
        : <span className={`qcs-owner-icon${icon ? "" : " blank"}`}>{icon && <LineIcon name={icon} size={14} />}</span>}
      <span className="qcs-owner-text">
        <b className={muted ? "muted" : undefined}>{title}</b>
        <small>{sub}</small>
      </span>
    </>
  );
}

/** Who has the stage, or where its work stands when nobody is named for it. */
function ownerOf(s: StageRow, userId: number | undefined): ReactNode {
  if (s.status === "NOT_APPLICABLE") return <Owner title="—" sub="Does not apply" muted />;
  const holder = s.assignment?.holder;
  // A batch-record stage that is signed through, or signed by someone with nobody named, shows its last signer.
  const lastSigned = columnsOf(s).map((c) => c.signature).filter((g) => g !== null)
    .sort((a, b) => (a.at < b.at ? 1 : -1))[0];
  if (lastSigned && (s.status === "PASSED" || !holder)) {
    return <Owner avatar={lastSigned.by.name} title={lastSigned.by.id === userId ? "You" : lastSigned.by.name}
      sub={s.status === "PASSED" ? "Signed last" : "Signed so far"} />;
  }
  if (holder) return <Owner avatar={holder.name} title={holder.id === userId ? "You" : holder.name} sub="Assigned" />;
  if (s.record) {
    return s.assignment?.required
      ? <Owner title="Unassigned" sub="Waits to be named" muted />
      : <Owner icon="people" title="Open to anyone" sub="Who fills batch records" muted />;
  }
  if (s.kind === "TESTED") {
    const n = s.samples.length + s.hidden_samples;
    return n
      ? <Owner icon="flask" title={`${n} sample${n === 1 ? "" : "s"}`} sub={s.samples[0]?.status_label ?? "Not yours to open"} />
      : <Owner icon="flask" title="No sample yet" sub="Registered at the front desk" muted />;
  }
  const last = s.records[0];
  return last
    ? <Owner avatar={last.recorded_by?.name ?? "QA"} title={last.recorded_by?.name ?? "QA"} sub={last.label} />
    : <Owner icon="sign" title="QA" sub="Not recorded yet" muted />;
}

type Show = "all" | "mine" | "todo" | "done";
const DONE_STATES = ["PASSED", "NOT_APPLICABLE"];

/**
 * The QC stages this batch goes through, as they were when it was created, any
 * added to it alone, and where each stands. Release waits for every required one
 * that applies to the batch.
 *
 * Each stage opens and closes. An administrator sees them all closed, to open the
 * one they want; anyone else sees open only the stages waiting on them (assigned to
 * them, theirs to fill, sign or record, or needing a sample they register), and the
 * one a task link points at.
 */
export default function BatchStages({ batch, onChange }: {
  batch: BatchDetail;
  onChange: (next: BatchDetail) => void;
}) {
  const toast = useToast();
  const view = batch.qc_stages;
  const [recording, setRecording] = useState<StageRow | null>(null);
  const [decision, setDecision] = useState<"PASSED" | "FAILED">("PASSED");
  const [password, setPassword] = useState("");
  // Marking a stage not applicable to this batch, or applicable again.
  const [marking, setMarking] = useState<{ stage: StageRow; applies: boolean } | null>(null);
  // A stage for this batch alone.
  const [adding, setAdding] = useState(false);
  const [extra, setExtra] = useState({ name: "", kind: "TESTED" as StageKind, tests: "", required: true, description: "" });
  // Naming who fills a batch-record stage and signs its first column.
  const { user, can } = useAuth();
  const [assigning, setAssigning] = useState<StageRow | null>(null);
  const [assignee, setAssignee] = useState("");
  // An administrator may do every stage, so none is singled out as theirs: all start closed.
  const admin = can("admin.override");
  // The stages open now. Worked out once, when the page opens: an action does not fold them away.
  const [open, setOpen] = useState<Set<number>>(() => {
    const ids = new Set<number>();
    if (!view || admin) return ids;
    for (const st of view.stages) if (forYou(st, view, user?.id)) ids.add(st.id);
    return ids;
  });
  const toggle = (id: number) => setOpen((now) => {
    const next = new Set(now);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
  // A link to one stage ("#stage-12", from a task or the progress bar above) opens it, also
  // when it is followed on this page.
  const location = useLocation();
  useEffect(() => {
    const linked = location.hash.match(/^#stage-(\d+)$/);
    if (!linked) return;
    const id = Number(linked[1]);
    setOpen((now) => (now.has(id) ? now : new Set(now).add(id)));
  }, [location.key, location.hash]);

  // Which stages the list shows: all, the person's own, the ones still to do, or the done.
  const [show, setShow] = useState<Show>("all");
  // An open stage's head stays in view under the top bar while its record is scrolled.
  const cardRef = useRef<HTMLElement>(null);

  // Opened from a task ("#stage-12"): bring that stage into view once it is drawn.
  const hasView = Boolean(view);
  useEffect(() => {
    const bar = document.querySelector<HTMLElement>(".topbar");
    const card = cardRef.current;
    if (!bar || !card) return;
    const place = () => card.style.setProperty(
      "--qcs-sticky", `${(parseFloat(getComputedStyle(bar).top) || 0) + bar.offsetHeight + 8}px`,
    );
    place();
    const watch = new ResizeObserver(place);
    watch.observe(bar);
    return () => watch.disconnect();
  }, [hasView]);
  useEffect(() => {
    const hash = window.location.hash;
    if (hasView && hash.startsWith("#stage-")) {
      document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  }, [hasView]);

  if (!view) return null;
  const close = () => {
    setRecording(null);
    setMarking(null);
    setAdding(false);
    setDecision("PASSED");
    setPassword("");
    setExtra({ name: "", kind: "TESTED", tests: "", required: true, description: "" });
    setAssigning(null);
    setAssignee("");
  };
  const openAssign = (s: StageRow) => {
    const a = s.assignment;
    // The first person it can go to who does not already have it.
    setAssignee(String(a?.people.find((p) => p.id !== a.holder?.id)?.id ?? ""));
    setAssigning(s);
  };
  // The column the assignee signs: "Done by", or the stage's own first one.
  const firstColumn = (s: StageRow) =>
    s.record?.signoffs[0]?.title ?? s.record?.steps[0]?.signoffs[0]?.title ?? "its first column";
  const complete = view.required > 0 && view.passed === view.required;
  // A stage added to one batch is lab-tested or QA pass / fail; only the kinds the lab
  // offers now (stageKinds.ts). None offered: no adding. The batch's own stages, their
  // samples and "Register a sample" are untouched either way.
  const addKinds = view.kinds.filter((k) => modeShown(k.value === "TESTED" ? "TESTED" : "QA"));
  const filters: { key: Show; label: string; match: (st: StageRow) => boolean }[] = [
    { key: "all", label: "All", match: () => true },
    ...(admin ? [] : [{ key: "mine" as Show, label: "For you", match: (st: StageRow) => Boolean(forYou(st, view, user?.id)) }]),
    { key: "todo", label: "To do", match: (st: StageRow) => !DONE_STATES.includes(st.status) },
    { key: "done", label: "Done", match: (st: StageRow) => DONE_STATES.includes(st.status) },
  ];
  const counted = filters.map((f) => ({ ...f, n: view.stages.filter(f.match).length }))
    .filter((f) => f.key === "all" || f.key === show || f.n > 0);
  const shown = view.stages.filter((filters.find((f) => f.key === show) ?? filters[0]).match);
  const allOpen = shown.length > 0 && shown.every((st) => open.has(st.id));
  // Stages of a batch that works by assignment, with nobody named yet: said once, to who names them.
  const unnamed = view.stages.filter((st) => st.assignment?.required && !st.assignment.holder
    && !DONE_STATES.includes(st.status)).length;
  const canName = view.stages.some((st) => st.assignment?.can_assign);

  return (
    <section className="card qcs-card" aria-label="QC stages" ref={cardRef}>
      <div className="card-head">
        <h2>QC stages</h2>
        <span className="hint">
          {view.version !== null
            ? `Version ${view.version} of the product's stages, fixed when the batch was created`
            : "Stages added to this batch alone"}
        </span>
        <div className="spacer" />
        {view.required > 0 && (
          <span className={`badge ${complete ? "pass" : "muted"}`}>
            {view.passed} of {view.required} required passed
          </span>
        )}
        {view.can_record && addKinds.length > 0 && (
          <button className="ghost small" onClick={() => {
            setExtra((x) => ({ ...x, kind: addKinds[0].value }));
            setAdding(true);
          }}>+ Add a stage for this batch</button>
        )}
      </div>
      {view.required > 0 && (
        <div className="qcs-progress" aria-hidden="true">
          <span style={{ width: `${(100 * view.passed) / view.required}%` }} />
        </div>
      )}
      {view.stages.length > 1 && (
        <div className="qcs-toolbar">
          <div className="qcs-chips" role="group" aria-label="Show stages">
            {counted.map((f) => (
              <button key={f.key} type="button" className={`qcs-chip${show === f.key ? " on" : ""}`}
                aria-pressed={show === f.key} onClick={() => setShow(f.key)}>
                {f.label} <span className="qcs-chip-n">{f.n}</span>
              </button>
            ))}
          </div>
          {canName && unnamed > 0 && (
            <span className="qcs-toolbar-note">
              {unnamed} stage{unnamed === 1 ? "" : "s"} still wait{unnamed === 1 ? "s" : ""} for someone to be named
            </span>
          )}
          <div className="spacer" />
          {shown.length > 0 && (
            <button className="subtle small" onClick={() => setOpen((now) => {
              const next = new Set(now);
              for (const st of shown) {
                if (allOpen) next.delete(st.id);
                else next.add(st.id);
              }
              return next;
            })}>
              {allOpen ? "Close all" : "Open all"}
            </button>
          )}
        </div>
      )}
      {view.stages.length === 0 ? (
        <div className="card-body">
          <p className="hint" style={{ margin: 0 }}>
            This batch has no QC stages. Its release waits on its samples alone, unless a stage is added for it.
          </p>
        </div>
      ) : shown.length === 0 ? (
        <div className="card-body">
          <p className="hint" style={{ margin: 0 }}>No stage of this batch is {show === "mine" ? "waiting on you" : show === "done" ? "done yet" : "left to do"}.</p>
        </div>
      ) : (
        <>
        <div className="qcs-cols" aria-hidden="true">
          <span>Stage</span><span>Who</span><span>Sign-offs</span><span>Status</span><span />
        </div>
        <ol className="qcs-list">
          {shown.map((s) => {
            const notApplicable = s.status === "NOT_APPLICABLE";
            const waiting = s.waiting_for.length > 0 && !notApplicable && s.status === "NOT_STARTED";
            const latestMark = s.applicability[0];
            const isOpen = open.has(s.id);
            const mine = admin ? "" : forYou(s, view, user?.id);
            const kind = kindOf(s);
            const columns = columnsOf(s);
            const signed = columns.filter((c) => c.signature).length;
            return (
              <li key={s.id} id={`stage-${s.id}`} className={`qcs-item qcs-fold ${s.status.toLowerCase()} ${isOpen ? "open" : "closed"}`}
                style={{ scrollMarginTop: 96 }}>
                <span className="qcs-num" aria-hidden="true">
                  {s.status === "PASSED" ? "✓" : s.status === "FAILED" ? "✕" : s.order}
                </span>
                <div className="qcs-body">
                  <button type="button" className="qcs-head" aria-expanded={isOpen}
                    aria-controls={`stage-body-${s.id}`} onClick={() => toggle(s.id)}>
                    <span className="qcs-head-main">
                      <span className="qcs-head-name">
                        <b>{s.name}</b>
                        {mine && <span className="badge hot">{mine}</span>}
                        {s.added_to_batch && <span className="badge info">Added to this batch</span>}
                        {!s.required && <span className="tag soft">Optional</span>}
                      </span>
                      <span className="qcs-head-meta">
                        <span className="qcs-kind"><LineIcon name={kind.icon} size={13} />{kind.label}</span>
                        {notApplicable && <span className="qcs-fact">Does not apply to this batch</span>}
                        {waiting && <span className="qcs-fact qcs-fact-warn">Waits for {s.waiting_for.join(", ")}</span>}
                      </span>
                    </span>
                    <span className="qcs-owner">{ownerOf(s, user?.id)}</span>
                    <span className="qcs-signs">
                      {columns.length > 0 && !notApplicable ? (
                        <span className="qcs-meter" title={`${signed} of ${columns.length} sign-offs given`}>
                          <span className="qcs-meter-bar"><i style={{ width: `${(100 * signed) / columns.length}%` }} /></span>
                          <small>{signed}/{columns.length}</small>
                        </span>
                      ) : (
                        <span className="qcs-none" title="Signed on its sample's certificate, or recorded by QA">—</span>
                      )}
                    </span>
                    <span className={`badge ${TONES[s.status]} qcs-status`}>{s.status_label}</span>
                    <span className="qcs-chev" aria-hidden="true">
                      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2"
                        strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6" /></svg>
                    </span>
                  </button>
                  {isOpen && (
                    <div className="qcs-open" id={`stage-body-${s.id}`}>
                      {s.description && <div className="cell-sub">{s.description}</div>}
                      {s.added_to_batch && s.added_by && (
                        <div className="cell-sub">
                          Added by {s.added_by.name}{s.added_at && <>, <Stamp at={s.added_at} /></>}
                          {s.added_reason && <> — “{s.added_reason}”</>}
                        </div>
                      )}
                      {notApplicable && latestMark && (
                        <div className="qcs-note">
                          Does not apply to this batch — “{latestMark.reason}”, {latestMark.recorded_by?.name},{" "}
                          <Stamp at={latestMark.recorded_at} />
                        </div>
                      )}
                      {s.assignment && !notApplicable && (
                        <div className={`qcs-assign${s.assignment.holder?.id === user?.id ? " mine" : ""}`}>
                          <span className="qcs-assign-who">
                            {s.assignment.holder ? (
                              <>
                                Assigned to <b>{s.assignment.holder.id === user?.id ? "you" : s.assignment.holder.name}</b>
                                {s.assignment.by && (
                                  <span className="cell-sub">
                                    {" "}· by {s.assignment.by.name}{s.assignment.at && <>, <Stamp at={s.assignment.at} /></>}
                                  </span>
                                )}
                                {s.assignment.note && <span className="cell-sub"> — “{s.assignment.note}”</span>}
                              </>
                            ) : s.assignment.required ? (
                              <span className="qcs-assign-wait">
                                Not assigned yet: stages of this batch are assigned, so it waits for the production
                                supervisor to name who does it.
                              </span>
                            ) : (
                              <span className="cell-sub">Not assigned: anyone who fills batch records can do it.</span>
                            )}
                          </span>
                          {s.assignment.can_assign && (
                            <button className="ghost small" onClick={() => openAssign(s)}>
                              {s.assignment.holder ? "Reassign…" : "Assign…"}
                            </button>
                          )}
                          {s.assignment.history.length > 1 && (
                            <details className="qcs-history qcs-assign-history">
                              <summary>Assignment history ({s.assignment.history.length})</summary>
                              <ul className="timeline">
                                {s.assignment.history.map((h, i) => (
                                  <li key={i}>
                                    <span className="when"><Stamp at={h.at} /></span>
                                    <span>
                                      <b>{h.by?.name}</b> {h.holder ? <>assigned it to <b>{h.holder.name}</b></> : "left it open to anyone"}
                                      {h.note && <span className="comment">“{h.note}”</span>}
                                    </span>
                                  </li>
                                ))}
                              </ul>
                            </details>
                          )}
                        </div>
                      )}
                      {waiting && (
                        <div className="qcs-note wait">
                          ⏸ Waits for {s.waiting_for.join(", ")} to pass first.
                        </div>
                      )}
    
                      {s.kind === "TESTED" && !notApplicable && (
                        <div className="qcs-detail">
                          {s.tests && <span className="cell-sub qcs-tests">Tested on: {s.tests}</span>}
                          {s.samples.length === 0 && s.hidden_samples === 0 ? (
                            <span className="cell-sub">No sample registered for this stage yet.</span>
                          ) : (
                            <>
                              {s.samples.map((x) => (
                                <Link key={x.id} className="tag soft" to={`/samples/${x.id}`}>
                                  {x.sample_no} · {x.status_label}
                                </Link>
                              ))}
                              {s.hidden_samples > 0 && (
                                <span className="cell-sub">and {s.hidden_samples} you cannot open</span>
                              )}
                            </>
                          )}
                        </div>
                      )}
    
                      {s.record && !notApplicable && (
                        <StageRecord batch={batch} stageId={s.id} record={s.record} onChange={onChange} />
                      )}
    
                      {s.kind === "RECORDED" && !s.record && !notApplicable && (
                        <div className="qcs-detail">
                          {s.records.length === 0 ? (
                            <span className="cell-sub">Not recorded yet.</span>
                          ) : (
                            <ul className="timeline">
                              {s.records.map((r) => (
                                <li key={r.id}>
                                  <span className="when"><Stamp at={r.recorded_at} /></span>
                                  <span>
                                    <b>{r.recorded_by?.name}</b>{" "}
                                    <span className={`badge ${r.decision === "PASSED" ? "pass" : "fail"}`}>{r.label}</span>
                                    {r.remarks && <span className="comment">“{r.remarks}”</span>}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      )}
    
                      {(view.can_record || view.can_register) && (
                        <div className="actions-bar qcs-actions-row">
                          {s.kind === "TESTED" && view.can_register && !notApplicable && (
                            waiting ? (
                              <button className="ghost small" disabled title={`Waits for ${s.waiting_for.join(", ")}`}>
                                Register a sample
                              </button>
                            ) : (
                              <Link className="link-button" to={registerLink(batch, s)}>Register a sample</Link>
                            )
                          )}
                          {s.kind === "RECORDED" && !s.record && view.can_record && !notApplicable && (
                            <button className="ghost small" disabled={waiting} onClick={() => setRecording(s)}
                              title={waiting ? `Waits for ${s.waiting_for.join(", ")}` : undefined}>
                              {s.records.length ? "Record again…" : "Record result…"}
                            </button>
                          )}
                          {view.can_record && s.status === "NOT_STARTED" && (
                            <button className="subtle small" onClick={() => setMarking({ stage: s, applies: false })}>
                              Not applicable to this batch…
                            </button>
                          )}
                          {view.can_record && notApplicable && (
                            <button className="ghost small" onClick={() => setMarking({ stage: s, applies: true })}>
                              It applies after all…
                            </button>
                          )}
                        </div>
                      )}
    
                      {s.applicability.length > (notApplicable ? 1 : 0) && (
                        <details className="qcs-history">
                          <summary>Applicability history ({s.applicability.length})</summary>
                          <ul className="timeline">
                            {s.applicability.map((m) => (
                              <li key={m.id}>
                                <span className="when"><Stamp at={m.recorded_at} /></span>
                                <span>
                                  <b>{m.recorded_by?.name}</b>{" "}
                                  <span className={`badge ${m.applies ? "info" : "muted"}`}>
                                    {m.applies ? "Applies again" : "Not applicable"}
                                  </span>
                                  <span className="comment">“{m.reason}”</span>
                                </span>
                              </li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
        </>
      )}

      {recording && (
        <CommentModal
          title={`Record “${recording.name}”`}
          hint="Signed with your password. A later record is added beside this one, never over it."
          label={decision === "FAILED" ? "Why did it fail?" : "Remarks (optional)"}
          optional={decision === "PASSED"}
          placeholder={decision === "FAILED"
            ? "What was found, e.g. material of the previous batch in the area."
            : "e.g. Area clean, 24 °C, 42 % RH, 10 Pa."}
          confirmText="Record result"
          tone="primary"
          onConfirm={async (remarks) => {
            onChange(await apiPost<BatchDetail>(`/api/batches/${batch.id}/qc-stages/${recording.id}/record/`, {
              decision, remarks, password,
            }));
            toast("ok", `${recording.name}: ${decision === "PASSED" ? "passed" : "failed"}`, "It is on the batch's record.");
            close();
          }}
          onClose={close}
        >
          <div className="field">
            Result
            <div className="seg" role="group" aria-label="Result">
              <button type="button" className={decision === "PASSED" ? "on" : ""} aria-pressed={decision === "PASSED"}
                onClick={() => setDecision("PASSED")}>Passed</button>
              <button type="button" className={decision === "FAILED" ? "on" : ""} aria-pressed={decision === "FAILED"}
                onClick={() => setDecision("FAILED")}>Failed</button>
            </div>
          </div>
          {decision === "FAILED" && recording.required && (
            <Message kind="warn">A failed required stage stops this batch from being released.</Message>
          )}
          <PasswordField value={password} onChange={setPassword} />
        </CommentModal>
      )}

      {marking && (
        <CommentModal
          title={marking.applies
            ? `“${marking.stage.name}” applies to this batch`
            : `“${marking.stage.name}” does not apply to this batch`}
          hint={marking.applies
            ? "It goes back to waiting for its samples or its record, and release waits for it again if it is required."
            : "Only this batch. The product's stages do not change, and release no longer waits for this stage. "
              + "Signed with your password; it can be undone, and both stay on the record."}
          label="Why?"
          placeholder={marking.applies
            ? "e.g. Marked by mistake; the line was used for another product in between."
            : "e.g. Same product on the same line, campaign batch 2 of 3 under change control CC-2026-0004."}
          confirmText={marking.applies ? "It applies" : "Not applicable"}
          tone="primary"
          onConfirm={async (reason) => {
            onChange(await apiPost<BatchDetail>(
              `/api/batches/${batch.id}/qc-stages/${marking.stage.id}/applicability/`,
              { applies: marking.applies, reason, password },
            ));
            toast("ok", marking.applies
              ? `${marking.stage.name} applies to this batch again`
              : `${marking.stage.name} marked not applicable`, "It is on the batch's record.");
            close();
          }}
          onClose={close}
        >
          <PasswordField value={password} onChange={setPassword} />
        </CommentModal>
      )}

      {adding && (
        <CommentModal
          title={`Add a stage to batch ${batch.official_batch_no}`}
          hint="For this batch alone: the product's stages do not change. It goes after the batch's other stages."
          label="Why does this batch need it?"
          placeholder="e.g. Reprocessed under deviation DEV-2026-0012: extra assay after re-blending."
          confirmText="Add stage"
          tone="primary"
          onConfirm={async (reason) => {
            onChange(await apiPost<BatchDetail>(`/api/batches/${batch.id}/qc-stages/`, {
              ...extra, tests: extra.kind === "TESTED" ? extra.tests : "", reason, password,
            }));
            toast("ok", `${extra.name.trim()} added to this batch`, "It is on the batch's record.");
            close();
          }}
          onClose={close}
        >
          <label className="field">
            Name
            <input value={extra.name} maxLength={80} required autoFocus
              onChange={(e) => setExtra((x) => ({ ...x, name: e.target.value }))}
              placeholder="e.g. Re-test after re-blending" />
          </label>
          <div className="form-row">
            <label className="field">
              How it is done
              <select value={extra.kind} onChange={(e) => setExtra((x) => ({ ...x, kind: e.target.value as StageKind }))}>
                {addKinds.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
              </select>
            </label>
            {extra.kind === "TESTED" ? (
              <label className="field">
                Its samples are tested on
                <select value={extra.tests} onChange={(e) => setExtra((x) => ({ ...x, tests: e.target.value }))}>
                  {view.tracks.map((t) => <option key={t.key} value={t.key}>{t.name}</option>)}
                </select>
              </label>
            ) : (
              <span className="cell-sub" style={{ alignSelf: "end" }}>QA records it passed or failed, with a password.</span>
            )}
          </div>
          <label className="switch-field">
            <span>Required for release</span>
            <input type="checkbox" role="switch" className="switch" checked={extra.required}
              onChange={(e) => setExtra((x) => ({ ...x, required: e.target.checked }))} />
          </label>
          <label className="field">
            <span>Description <span className="note">(optional)</span></span>
            <input value={extra.description} maxLength={300}
              onChange={(e) => setExtra((x) => ({ ...x, description: e.target.value }))} />
          </label>
          <PasswordField value={password} onChange={setPassword} />
        </CommentModal>
      )}

      {assigning?.assignment && (
        <CommentModal
          title={`${assigning.assignment.holder ? "Reassign" : "Assign"} “${assigning.name}”`}
          hint={`The person named fills its values and signs “${firstColumn(assigning)}”: until it is reassigned, only they can.`
            + " The columns after it are signed as before."
            + (assigning.assignment.required ? ""
              : " This is the first stage of the batch to be assigned: from now on each stage is filled only once"
                + " someone is assigned to it, and everyone still sees them all.")}
          label="Note (optional)"
          placeholder="e.g. Day shift, or why it is being reassigned"
          confirmText={assignee ? "Assign" : "Leave it open to anyone"}
          tone="primary"
          optional
          onConfirm={async (note) => {
            onChange(await apiPost<BatchDetail>(`/api/batches/${batch.id}/qc-stages/${assigning.id}/assign/`, {
              assignee_id: assignee ? Number(assignee) : null, note,
            }));
            const who = assigning.assignment?.people.find((p) => String(p.id) === assignee)?.name;
            toast("ok", who ? `${assigning.name}: assigned to ${who}` : `${assigning.name} is open to anyone`,
              who ? "It is in their My tasks. Only they fill it and sign its first column." : "Anyone who fills batch records can now do it.");
            close();
          }}
          onClose={close}
        >
          <label className="field">
            Assign to
            <select value={assignee} onChange={(e) => setAssignee(e.target.value)} autoFocus>
              {assigning.assignment.people.map((p) => (
                <option key={p.id} value={p.id} disabled={p.id === assigning.assignment?.holder?.id}>
                  {p.name} · {p.role}{p.id === assigning.assignment?.holder?.id ? " (has it now)" : ""}
                </option>
              ))}
              {assigning.assignment.holder && (
                <option value="">
                  {view.stages.some((x) => x.id !== assigning.id && x.assignment?.holder)
                    ? "Nobody: it waits until someone is assigned"
                    : "Nobody: anyone who fills batch records"}
                </option>
              )}
            </select>
            {assigning.assignment.people.length === 0 && (
              <span className="field-error">Nobody can take it: no one whose role signs “{firstColumn(assigning)}” may fill batch records.</span>
            )}
          </label>
        </CommentModal>
      )}
    </section>
  );
}
