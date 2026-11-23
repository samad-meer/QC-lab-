import { useEffect, useMemo, useRef, useState } from "react";
import { apiPost } from "../api";
import type { BatchDetail, BatchStageRecord, CheckpointKind, RecordColumn, RecordEntry, RecordFlag } from "../types";
import { fmtDate, nowLocalInput, todayInput, toLocalInput } from "../util";
import CommentModal from "./CommentModal";
import { Message } from "./Feedback";
import Stamp from "./Stamp";
import { useToast } from "./Toast";

type Point = BatchStageRecord["steps"][number]["checkpoints"][number];
type Step = BatchStageRecord["steps"][number];

/** What is typed for one check point, before it is saved. */
interface Typed {
  number: string;
  text: string;
  date: string;
  start: string;
  end: string;
  yes_no: "" | "yes" | "no";
  reason: string;
  correction: string;
}

const NUMERIC: CheckpointKind[] = ["NUMBER", "PERCENT"];

function fromEntry(e: RecordEntry | null): Typed {
  return {
    number: e?.number ?? "",
    text: e?.text ?? "",
    date: e?.date ?? "",
    start: e?.start ? toLocalInput(e.start) : "",
    end: e?.end ? toLocalInput(e.end) : "",
    yes_no: e?.yes_no === true ? "yes" : e?.yes_no === false ? "no" : "",
    reason: e?.reason ?? "",
    correction: "",
  };
}

/** The value part of what is typed, to tell whether it differs from what is saved. */
function valueOf(kind: CheckpointKind, t: Typed): string {
  switch (kind) {
    case "NUMBER":
    case "PERCENT": {
      const n = t.number.trim();
      return n === "" || Number.isNaN(Number(n)) ? n : String(Number(n));
    }
    case "TIME_RANGE": return t.start && t.end ? `${t.start}|${t.end}` : t.start || t.end ? "partial" : "";
    case "TIME": return t.start;
    case "DATE": return t.date;
    case "TEXT": return t.text.trim();
    case "CHOICE": return t.text;
    case "YES_NO": return t.yes_no;
  }
}

function outside(p: Point, t: Typed): boolean {
  if (p.kind === "CHOICE") return p.choices.some((c) => c.label === t.text && !c.ok);
  if (!NUMERIC.includes(p.kind) || t.number.trim() === "") return false;
  const n = Number(t.number);
  if (Number.isNaN(n)) return false;
  return (p.min_value !== null && n < Number(p.min_value)) || (p.max_value !== null && n > Number(p.max_value));
}

function ValueInput({ p, t, set }: { p: Point; t: Typed; set: (patch: Partial<Typed>) => void }) {
  const id = `cp-${p.id}`;
  switch (p.kind) {
    case "NUMBER":
    case "PERCENT":
      return (
        <span className="rec-number">
          <input id={id} inputMode="decimal" value={t.number} onChange={(e) => set({ number: e.target.value })}
            placeholder={p.decimals ? `0.${"0".repeat(p.decimals)}` : "0"} aria-label={p.label} />
          {p.unit && <span className="rec-unit">{p.unit}</span>}
        </span>
      );
    case "TIME_RANGE":
      return (
        <span className="rec-range">
          <label>Start
            <input type="datetime-local" value={t.start} onChange={(e) => set({ start: e.target.value })}
              aria-label={`${p.label}, start`} />
          </label>
          <button type="button" className="link-btn" onClick={() => set({ start: nowLocalInput() })}>Now</button>
          <label>End
            <input type="datetime-local" value={t.end} onChange={(e) => set({ end: e.target.value })}
              aria-label={`${p.label}, end`} />
          </label>
          <button type="button" className="link-btn" onClick={() => set({ end: nowLocalInput() })}>Now</button>
        </span>
      );
    case "TIME":
      return (
        <span className="rec-range">
          <input type="datetime-local" value={t.start} onChange={(e) => set({ start: e.target.value })} aria-label={p.label} />
          <button type="button" className="link-btn" onClick={() => set({ start: nowLocalInput() })}>Now</button>
        </span>
      );
    case "DATE":
      return <input type="date" value={t.date} max={todayInput()} onChange={(e) => set({ date: e.target.value })} aria-label={p.label} />;
    case "TEXT":
      return <input value={t.text} maxLength={1000} onChange={(e) => set({ text: e.target.value })} aria-label={p.label} />;
    case "CHOICE":
      return (
        <select value={t.text} onChange={(e) => set({ text: e.target.value })} aria-label={p.label} style={{ width: "auto" }}>
          <option value="">— choose —</option>
          {p.choices.map((c) => <option key={c.label} value={c.label}>{c.label}</option>)}
        </select>
      );
    case "YES_NO":
      return (
        <div className="seg" role="group" aria-label={p.label}>
          {(["yes", "no"] as const).map((v) => (
            <button key={v} type="button" className={t.yes_no === v ? "on" : ""} aria-pressed={t.yes_no === v}
              onClick={() => set({ yes_no: v })}>{v === "yes" ? "Yes" : "No"}</button>
          ))}
        </div>
      );
  }
}

/** The sign-off columns of a stage, or of one step: each signed with a password, in order. */
function SignRow({ columns, label, withDate, onSign }: {
  columns: RecordColumn[];
  label: string;
  /** Signed under a step: a Date cell first, as the paper record has it. */
  withDate?: boolean;
  onSign: (c: RecordColumn) => void;
}) {
  const first = columns[0]?.signature;
  return (
    <div className={`rec-signoffs${withDate ? " rec-step-signs" : ""}`} role="table" aria-label={label}>
      {withDate && (
        <div className={`rec-signoff rec-date${first ? " signed" : ""}`} role="row">
          <div className="rec-signoff-title" role="cell"><b>Date</b><span className="cell-sub">When it was done</span></div>
          <div role="cell">{first ? <b>{fmtDate(first.at)}</b> : <span className="cell-sub">Not signed yet</span>}</div>
        </div>
      )}
      {columns.map((c) => (
        <div className={`rec-signoff${c.signature ? " signed" : ""}`} key={c.id} role="row">
          <div className="rec-signoff-title" role="cell">
            <b>{c.title}</b>
            <span className="cell-sub">{c.holder || c.role}</span>
          </div>
          <div role="cell">
            {c.signature ? (
              <>
                <b>{c.signature.by?.name}</b>
                <div className="cell-sub"><Stamp at={c.signature.at} /></div>
                {c.signature.acknowledged && <div className="cell-sub">Acknowledged the values out of limit</div>}
                {c.signature.comment && <div className="rec-quote">“{c.signature.comment}”</div>}
              </>
            ) : c.blocked ? (
              <span className="cell-sub">{c.blocked}</span>
            ) : (
              <button className="primary small" onClick={() => onSign(c)}>Sign “{c.title}”…</button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * A recorded stage of a batch, as the paper batch record has it: each step with its
 * instructions and the values it asks for, and the sign-off columns, signed in
 * order: once at the end of the stage, or under every step when the stage is
 * signed at every step. A value outside its limits is flagged and carries why; the
 * last column acknowledges it.
 */
export default function StageRecord({ batch, stageId, record, onChange }: {
  batch: BatchDetail;
  stageId: number;
  record: BatchStageRecord;
  onChange: (next: BatchDetail) => void;
}) {
  const toast = useToast();
  const points = useMemo(() => record.steps.flatMap((s) => s.checkpoints), [record]);
  const [typed, setTyped] = useState<Record<number, Typed>>(() => Object.fromEntries(points.map((p) => [p.id, fromEntry(p.entry)])));
  const [error, setError] = useState<{ step: number | null; text: string } | null>(null);
  // Reason boxes still to fill before the values can be saved: "why-<id>" (out of limit),
  // "fix-<id>" (changing a value already on the record).
  const [needReason, setNeedReason] = useState<Set<string>>(new Set());
  const reasonGiven = (key: string) =>
    setNeedReason((s) => (s.has(key) ? new Set([...s].filter((k) => k !== key)) : s));
  const [busy, setBusy] = useState(false);
  const [signing, setSigning] = useState<{ column: RecordColumn; step: Step | null } | null>(null);
  const [password, setPassword] = useState("");
  const [acknowledge, setAcknowledge] = useState(false);
  // Saved or signed: a value whose entry changed starts again from what the record now
  // says; what is still being typed elsewhere stays.
  const seen = useRef<Record<number, number | null>>({});
  useEffect(() => {
    const before = seen.current;
    seen.current = Object.fromEntries(points.map((p) => [p.id, p.entry?.id ?? null]));
    setTyped((prev) => Object.fromEntries(points.map((p) => [
      p.id, prev[p.id] && before[p.id] !== undefined && before[p.id] === (p.entry?.id ?? null) ? prev[p.id] : fromEntry(p.entry),
    ])));
  }, [points]);

  const set = (id: number, patch: Partial<Typed>) => setTyped((all) => ({ ...all, [id]: { ...all[id], ...patch } }));
  const changed = (p: Point) => valueOf(p.kind, typed[p.id]) !== valueOf(p.kind, fromEntry(p.entry));
  const canFill = (step: Step) => record.can_fill && !step.locked;
  const dirtyIn = (steps: Step[]) =>
    steps.filter(canFill).flatMap((s) => s.checkpoints).filter((p) => changed(p) && valueOf(p.kind, typed[p.id]) !== "");

  const save = async (dirty: Point[], step: Step | null) => {
    // The server asks for these reasons too; asked here first, at the box that takes them.
    const missing = dirty.flatMap((p) => {
      const t = typed[p.id];
      const out: { key: string; text: string }[] = [];
      if (outside(p, t) && !t.reason.trim()) {
        out.push({ key: `why-${p.id}`, text: `“${p.label}” is out of limit: say why in the box under it.` });
      }
      if (p.entry !== null && !t.correction.trim()) {
        out.push({ key: `fix-${p.id}`, text: `“${p.label}” already reads ${p.entry.shown}: say why it is being changed, in the box under it.` });
      }
      return out;
    });
    if (missing.length) {
      const text = missing.length === 1 ? missing[0].text
        : `${missing.length} values need a reason before they are saved — the boxes outlined in red.`;
      setNeedReason(new Set(missing.map((m) => m.key)));
      setError({ step: step?.id ?? null, text });
      toast("error", "Not saved", text);
      requestAnimationFrame(() => {
        const first = document.getElementById(missing[0].key);
        first?.scrollIntoView({ block: "center", behavior: "smooth" });
        first?.focus({ preventScroll: true });
      });
      return;
    }
    setNeedReason(new Set());
    setBusy(true);
    setError(null);
    try {
      const entries = dirty.map((p) => {
        const t = typed[p.id];
        const value = NUMERIC.includes(p.kind) ? { number: t.number.trim() }
          : p.kind === "TIME_RANGE" ? { start: t.start, end: t.end }
          : p.kind === "TIME" ? { start: t.start }
          : p.kind === "DATE" ? { date: t.date }
          : p.kind === "YES_NO" ? { yes_no: t.yes_no === "yes" }
          : { text: t.text };
        return { checkpoint_id: p.id, ...value, reason: t.reason, correction: t.correction };
      });
      onChange(await apiPost<BatchDetail>(`/api/batches/${batch.id}/qc-stages/${stageId}/entries/`, { entries }));
      // Say what was saved, by name, and where.
      const names = dirty.map((p) => p.label);
      const listed = names.length <= 3 ? names.join(", ") : `${names.slice(0, 3).join(", ")} and ${names.length - 3} more`;
      toast("ok", names.length === 1 ? `Saved: ${names[0]}` : `${names.length} values saved`,
        `${names.length === 1 ? "" : `${listed}. `}${step?.title ? `${step.title}, ` : ""}on the batch record with your name and the time.`);
    } catch (err) {
      setError({ step: step?.id ?? null, text: err instanceof Error ? err.message : "Could not save the values." });
    } finally {
      setBusy(false);
    }
  };

  const closeSign = () => {
    setSigning(null);
    setPassword("");
    setAcknowledge(false);
  };
  // What the column being signed acknowledges: its step's values out of limit, or the stage's.
  const flags: RecordFlag[] = signing?.column.acknowledges ? (signing.step ? signing.step.out_of_limit : record.out_of_limit) : [];
  const needsAck = flags.length > 0;
  const firstColumn = signing ? (signing.step ? signing.step.signoffs[0] : record.signoffs[0]) : null;

  const saveBar = (dirty: Point[], missing: string[], step: Step | null) => (
    <div className={`actions-bar rec-save${step ? " rec-step-save" : ""}`}>
      <span className="cell-sub">
        {dirty.length
          ? `${dirty.length} value${dirty.length === 1 ? "" : "s"} to save`
          : missing.length ? `${missing.length} required value${missing.length === 1 ? "" : "s"} still to write`
          : step ? "Every value of this step is written." : "Every value is written."}
      </span>
      <div className="spacer" />
      <button className="primary small" disabled={busy || dirty.length === 0} onClick={() => void save(dirty, step)}>
        {busy ? "Saving…"
          : dirty.length === 0 && missing.length === 0 ? "✓ All saved"
          : step ? "Save this step" : "Save values"}
      </button>
    </div>
  );
  const errorFor = (step: Step | null) =>
    error && error.step === (step?.id ?? null) ? <Message kind="error">{error.text}</Message> : null;

  return (
    <div className="rec">
      {record.steps.map((step) => {
        const fill = canFill(step);
        return (
          <div className={`rec-step${record.per_step && step.locked ? " locked" : ""}`} key={step.id}>
            <div className="rec-step-head">
              <span className="rec-step-num">{step.order}</span>
              <b>{step.title}</b>
              {record.per_step && step.signoffs.length > 0 && (
                step.signoffs.every((c) => c.signature) ? <span className="badge pass">Signed</span>
                  : step.locked ? <span className="badge">Being signed</span> : null
              )}
            </div>
            {step.instructions && <div className="rec-instructions">{step.instructions}</div>}
            {step.checkpoints.length > 0 && (
              <div className="rec-points">
                {step.checkpoints.map((p) => {
                  const t = typed[p.id] ?? fromEntry(p.entry);
                  const flagged = fill ? outside(p, t) : Boolean(p.entry?.out_of_limit);
                  const isChanged = fill && p.entry !== null && changed(p) && valueOf(p.kind, t) !== "";
                  return (
                    <div className={`rec-point${flagged ? " flagged" : ""}`} key={p.id}>
                      <div className="rec-label">
                        <label htmlFor={`cp-${p.id}`}>{p.label}</label>
                        {p.required ? null : <span className="note"> (optional)</span>}
                        {p.limit_text && <div className="cell-sub">{p.kind === "CHOICE" ? p.limit_text : `Limit: ${p.limit_text}`}</div>}
                      </div>
                      <div className="rec-value">
                        {fill ? (
                          <ValueInput p={p} t={t} set={(patch) => set(p.id, patch)} />
                        ) : p.entry ? (
                          <span className="rec-shown">{p.entry.shown}</span>
                        ) : (
                          <span className="cell-sub">Not written</span>
                        )}
                        {flagged && <span className="badge fail">Out of limit</span>}
                        {fill && flagged && (
                          <input className="rec-why" id={`why-${p.id}`} value={t.reason} maxLength={500}
                            onChange={(e) => { set(p.id, { reason: e.target.value }); reasonGiven(`why-${p.id}`); }}
                            data-flagged={needReason.has(`why-${p.id}`) ? "" : undefined}
                            aria-invalid={needReason.has(`why-${p.id}`) || undefined}
                            placeholder="Why is it outside the limit? QA acknowledges it." aria-label={`${p.label}: why out of limit`} />
                        )}
                        {isChanged && <span className="cell-sub rec-was">Was {p.entry!.shown}</span>}
                        {isChanged && (
                          <input className="rec-why" id={`fix-${p.id}`} value={t.correction} maxLength={500}
                            onChange={(e) => { set(p.id, { correction: e.target.value }); reasonGiven(`fix-${p.id}`); }}
                            data-flagged={needReason.has(`fix-${p.id}`) ? "" : undefined}
                            aria-invalid={needReason.has(`fix-${p.id}`) || undefined}
                            placeholder="Why change it? (required)" title={`It read ${p.entry!.shown}. Why change it?`}
                            aria-label={`${p.label}: why changed`} />
                        )}
                        {!fill && p.entry?.out_of_limit && p.entry.reason && (
                          <span className="rec-quote">“{p.entry.reason}”</span>
                        )}
                      </div>
                      <div className="rec-by">
                        {p.entry && (
                          <>
                            <span>{p.entry.entered_by?.name}</span>
                            <span className="cell-sub"><Stamp at={p.entry.entered_at} /></span>
                            {p.history.length > 0 && (
                              <details className="rec-history">
                                <summary>Changed {p.history.length} time{p.history.length === 1 ? "" : "s"}</summary>
                                <ul>
                                  {[p.entry, ...p.history].map((h, i, all) => (
                                    <li key={h.id}>
                                      <b>{h.shown}</b> · {h.entered_by?.name}, <Stamp at={h.entered_at} />
                                      {i < all.length - 1 && all[i].correction && <span className="rec-quote"> “{all[i].correction}”</span>}
                                    </li>
                                  ))}
                                </ul>
                              </details>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            {record.per_step && (
              <div className="rec-step-foot">
                {fill && step.checkpoints.length > 0 && saveBar(dirtyIn([step]), step.missing, step)}
                {errorFor(step)}
                <SignRow columns={step.signoffs} label={`Step ${step.order} sign-offs`} withDate
                  onSign={(column) => setSigning({ column, step })} />
              </div>
            )}
          </div>
        );
      })}

      {!record.per_step && record.can_fill && points.length > 0 && saveBar(dirtyIn(record.steps), record.missing, null)}
      {errorFor(null)}
      {!record.can_fill && record.fill_blocked && !record.locked && (
        <div className="cell-sub">{record.fill_blocked}</div>
      )}
      {!record.per_step && (
        <SignRow columns={record.signoffs} label="Sign-off columns" onSign={(column) => setSigning({ column, step: null })} />
      )}

      {signing && (
        <CommentModal
          title={`Sign “${signing.column.title}${signing.column.holder ? ` (${signing.column.holder})` : ""}”${signing.step ? ` for step ${signing.step.order}, ${signing.step.title}` : ""}`}
          hint={firstColumn && firstColumn.id !== signing.column.id
            ? "Signed with your password, in your name. It cannot be undone."
            : signing.step
              ? "Signed with your password, in your name. Once this first column is signed, the values of this step are final."
              : "Signed with your password, in your name. Once this first column is signed, the values of this stage are final."}
          label={needsAck ? "Your comment on the values out of limit" : "Comment (optional)"}
          optional={!needsAck}
          placeholder={needsAck ? "e.g. Reviewed: re-dried, LOD 3.9 % on recheck; deviation DEV-2026-0012." : "Anything the record should say."}
          confirmText="Sign"
          tone="primary"
          onConfirm={async (comment) => {
            onChange(await apiPost<BatchDetail>(`/api/batches/${batch.id}/qc-stages/${stageId}/sign/`, {
              signoff_id: signing.column.id, password, comment, acknowledge,
              ...(signing.step ? { step_id: signing.step.id } : {}),
            }));
            toast("ok", `Signed “${signing.column.title}”`, signing.step ? `Step ${signing.step.order}, ${signing.step.title}.` : "It is on the batch record.");
            closeSign();
          }}
          onClose={closeSign}
        >
          {needsAck && (
            <>
              <Message kind="warn">
                <b>{flags.length} value{flags.length === 1 ? " is" : "s are"} out of limit.</b>
                {flags.map((o) => (
                  <div key={o.label}>{o.label}: {o.shown} (limit {o.limit}) — “{o.reason}”</div>
                ))}
              </Message>
              <label className="cl-flag">
                <input type="checkbox" checked={acknowledge} onChange={(e) => setAcknowledge(e.target.checked)} />
                I have reviewed these values
              </label>
            </>
          )}
          <label className="field">
            Your password <span className="note">this is a signature</span>
            <input type="password" required autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </label>
        </CommentModal>
      )}
    </div>
  );
}
