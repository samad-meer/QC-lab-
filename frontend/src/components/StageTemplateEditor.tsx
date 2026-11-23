import { useState } from "react";
import type { CheckpointKind, CheckpointPreset, ChoiceOption, QcStagePlanStage } from "../types";
import { BLANK_CHOICES, BUILT_IN, ChoiceOptions, KindModal } from "./CheckpointKindForm";
import RowTools from "./RowTools";

export interface DraftPoint {
  key: number;
  label: string;
  kind: CheckpointKind;
  unit: string;
  min_value: string;
  max_value: string;
  decimals: number;
  required: boolean;
  /** A choice's options, with which answers are acceptable. */
  choices: ChoiceOption[];
  /** The lab's own kind it came from, such as Temperature; empty for a built-in kind. */
  kind_name: string;
}

export interface DraftStep {
  key: number;
  title: string;
  instructions: string;
  checkpoints: DraftPoint[];
}

export interface DraftSignoff {
  key: number;
  title: string;
  holder: string;
  role_id: string;
}

let nextKey = 1;
const fresh = () => nextKey++;
const NUMERIC: CheckpointKind[] = ["NUMBER", "PERCENT"];

/** A saved stage's steps and sign-off columns, as the editor holds them. */
export function toDraft(stage: QcStagePlanStage): { steps: DraftStep[]; signoffs: DraftSignoff[]; sign_each_step: boolean } {
  return {
    sign_each_step: stage.sign_each_step,
    steps: stage.steps.map((st) => ({
      key: fresh(), title: st.title, instructions: st.instructions,
      checkpoints: st.checkpoints.map((cp) => ({
        key: fresh(), label: cp.label, kind: cp.kind, unit: cp.unit, min_value: cp.min_value ?? "",
        max_value: cp.max_value ?? "", decimals: cp.decimals, required: cp.required,
        choices: cp.choices ?? [], kind_name: cp.kind_name ?? "",
      })),
    })),
    signoffs: stage.signoffs.map((so) => ({ key: fresh(), title: so.title, holder: so.holder, role_id: String(so.role_id) })),
  };
}

/** What the server is sent for one stage's steps and sign-off columns. */
export function toPayload(steps: DraftStep[], signoffs: DraftSignoff[], signEachStep: boolean) {
  return {
    sign_each_step: signEachStep,
    steps: steps.map((st) => ({
      title: st.title, instructions: st.instructions,
      checkpoints: st.checkpoints.map((cp) => ({
        label: cp.label, kind: cp.kind, unit: cp.kind === "NUMBER" ? cp.unit : "",
        min_value: NUMERIC.includes(cp.kind) && cp.min_value.trim() ? cp.min_value.trim() : null,
        max_value: NUMERIC.includes(cp.kind) && cp.max_value.trim() ? cp.max_value.trim() : null,
        decimals: cp.decimals, required: cp.required, kind_name: cp.kind_name,
        choices: cp.kind === "CHOICE" ? cp.choices.filter((c) => c.label.trim()) : [],
      })),
    })),
    signoffs: signoffs.map((so) => ({ title: so.title, holder: so.holder, role_id: so.role_id ? Number(so.role_id) : null })),
  };
}

function swap<T>(list: T[], i: number, by: number): T[] {
  const next = [...list];
  [next[i], next[i + by]] = [next[i + by], next[i]];
  return next;
}

const BLANK_POINT = (): DraftPoint => ({
  key: fresh(), label: "", kind: "NUMBER", unit: "", min_value: "", max_value: "", decimals: 2, required: true,
  choices: [], kind_name: "",
});

/** What a value with no unit or limits says in their place. */
const NO_LIMITS: Partial<Record<CheckpointKind, string>> = {
  TIME_RANGE: "A start and an end time: no unit or limits",
  TIME: "A time of day: no unit or limits",
  DATE: "A date: no unit or limits",
  TEXT: "Written text: no unit or limits",
  YES_NO: "Yes or no: no unit or limits",
  CHOICE: "One of the options below",
};

/** The limit as the record will print it, while it is typed: “Limit: 3.00 – 4.50 %”. */
function limitPreview(cp: DraftPoint): { text: string; wrong: boolean } | null {
  const lo = cp.min_value.trim();
  const hi = cp.max_value.trim();
  if (!lo && !hi) return null;
  const bad = [lo, hi].filter(Boolean).some((v) => Number.isNaN(Number(v)));
  if (bad) return { text: "A limit must be a number.", wrong: true };
  if (lo && hi && Number(lo) > Number(hi)) return { text: "The lower limit is above the upper limit.", wrong: true };
  const unit = cp.kind === "PERCENT" ? " %" : cp.unit.trim() ? ` ${cp.unit.trim()}` : "";
  const shown = (v: string) => Number(v).toFixed(cp.decimals);
  const text = lo && hi ? `${shown(lo)} – ${shown(hi)}${unit}` : lo ? `NLT ${shown(lo)}${unit}` : `NMT ${shown(hi)}${unit}`;
  return { text: `Limit: ${text}`, wrong: false };
}

/** What a check point takes from one of the lab's own kinds. */
function fromPreset(k: CheckpointPreset): Partial<DraftPoint> {
  return {
    kind: k.kind, kind_name: k.name, unit: k.unit, decimals: k.decimals,
    min_value: k.min_value ?? "", max_value: k.max_value ?? "", choices: k.choices.map((c) => ({ ...c })),
  };
}

/** A first step, ready to fill in: a title, its instructions and one check point. */
export function blankStep(): DraftStep {
  return { key: fresh(), title: "", instructions: "", checkpoints: [BLANK_POINT()] };
}

/**
 * One recorded stage's steps, with the values each asks for, and its sign-off
 * columns, in the order they are signed. What the paper batch record prints.
 */
export default function StageTemplateEditor({
  stageNo, steps, signoffs, signEachStep, presets, roles, onSteps, onSignoffs, onSignEachStep, onPresetAdded,
}: {
  stageNo: number;
  steps: DraftStep[];
  signoffs: DraftSignoff[];
  /** Signed under every step, as on the paper record, or once for the stage. */
  signEachStep: boolean;
  onSignEachStep: (next: boolean) => void;
  /** The lab's own kinds of value, offered after the built-in ones. */
  presets: CheckpointPreset[];
  roles: { id: number; name: string }[];
  onSteps: (next: DraftStep[]) => void;
  onSignoffs: (next: DraftSignoff[]) => void;
  onPresetAdded: (kind: CheckpointPreset) => void;
}) {
  // The check point a new kind is being made for, from “+ New kind…”.
  const [newKindFor, setNewKindFor] = useState<{ step: number; point: number } | null>(null);
  // Steps whose instructions box has been opened while still empty.
  const [writing, setWriting] = useState<Set<number>>(new Set());
  const points = steps.reduce((n, s) => n + s.checkpoints.length, 0);
  const editStep = (key: number, patch: Partial<DraftStep>) =>
    onSteps(steps.map((s) => (s.key === key ? { ...s, ...patch } : s)));
  const editPoint = (step: DraftStep, key: number, patch: Partial<DraftPoint>) =>
    editStep(step.key, { checkpoints: step.checkpoints.map((c) => (c.key === key ? { ...c, ...patch } : c)) });
  const editSignoff = (key: number, patch: Partial<DraftSignoff>) =>
    onSignoffs(signoffs.map((s) => (s.key === key ? { ...s, ...patch } : s)));

  // Done by (Operator) → Checked by (Production) → Checked by (QA), with the roles that fit.
  const usual = () => {
    const find = (...words: string[]) =>
      String(roles.find((r) => words.some((w) => r.name.toLowerCase().includes(w)))?.id ?? "");
    onSignoffs([
      ...signoffs,
      { key: fresh(), title: "Done by", holder: "Operator", role_id: find("operator") },
      { key: fresh(), title: "Checked by", holder: "Production", role_id: find("supervisor") },
      { key: fresh(), title: "Checked by", holder: "QA", role_id: find("qa", "lab head") },
    ]);
  };

  return (
    <div className="tpl">
      <section className="tpl-section" aria-label={`Stage ${stageNo} steps`}>
        <div className="tpl-section-head">
          <b>Steps</b>
          <span className="cell-sub">
            {steps.length} step{steps.length === 1 ? "" : "s"} · {points} check point{points === 1 ? "" : "s"} · as printed on the batch record
          </span>
        </div>
        {steps.map((step, i) => {
          const showInstructions = Boolean(step.instructions) || writing.has(step.key);
          return (
          <div className="tpl-step" key={step.key}>
            <div className="tpl-step-head">
              <span className="tpl-step-label">Step {i + 1}</span>
              <input className="tpl-step-title" value={step.title} maxLength={200}
                onChange={(e) => editStep(step.key, { title: e.target.value })}
                placeholder={i === 0 ? "Title, e.g. Premixing" : "Title, e.g. Preparation of binding solution"}
                aria-label={`Stage ${stageNo}, step ${i + 1} title`} />
              <RowTools noun="step" n={i + 1}
                onUp={i > 0 ? () => onSteps(swap(steps, i, -1)) : undefined}
                onDown={i < steps.length - 1 ? () => onSteps(swap(steps, i, 1)) : undefined}
                onRemove={() => onSteps(steps.filter((s) => s.key !== step.key))} />
            </div>
            {showInstructions ? (
              <textarea className="tpl-instructions" rows={2} maxLength={4000} value={step.instructions}
                autoFocus={!step.instructions}
                onChange={(e) => editStep(step.key, { instructions: e.target.value })}
                onBlur={() => !step.instructions && setWriting((w) => { const n = new Set(w); n.delete(step.key); return n; })}
                placeholder={"As printed on the record, e.g.\na) Clean the Sigma Mixer thoroughly and dry it.\nb) Load the material and mix for 20 minutes."}
                aria-label={`Step ${i + 1} instructions`} />
            ) : (
              <button type="button" className="link-btn tpl-add-instructions"
                onClick={() => setWriting((w) => new Set(w).add(step.key))}>
                + Add instructions
              </button>
            )}

            <div className="tpl-points" role="table" aria-label={`Step ${i + 1} check points`}>
              {step.checkpoints.length > 0 && (
                <div className="tpl-point tpl-point-head" role="row">
                  <span role="columnheader">Check point</span><span role="columnheader">Kind of value</span>
                  <span role="columnheader">Unit</span><span role="columnheader">Lower limit</span>
                  <span role="columnheader">Upper limit</span><span role="columnheader">Decimals</span>
                  <span role="columnheader" className="tpl-center">Required</span><span />
                </div>
              )}
              {step.checkpoints.map((cp, j) => {
                const numeric = NUMERIC.includes(cp.kind);
                // Which entry of the list it shows: one of the lab's own kinds by name, else the built-in kind.
                const preset = cp.kind_name ? presets.find((k) => k.name === cp.kind_name) : undefined;
                const listed = preset ? `P:${preset.id}` : `K:${cp.kind}`;
                const limit = numeric ? limitPreview(cp) : null;
                return (
                  <div className={`tpl-point-wrap${numeric ? "" : " plain"}`} key={cp.key}>
                    <div className="tpl-point" role="row">
                      <input value={cp.label} maxLength={200} onChange={(e) => editPoint(step, cp.key, { label: e.target.value })}
                        placeholder={j === 0 ? "e.g. Ciprofloxacin HCl" : "e.g. Start and end of mixing"}
                        aria-label={`Step ${i + 1}, check point ${j + 1}`} />
                      <select value={listed} aria-label={`Check point ${j + 1} kind`}
                        onChange={(e) => {
                          const picked = e.target.value;
                          if (picked === "+new") {
                            setNewKindFor({ step: step.key, point: cp.key });
                            return;
                          }
                          const own = picked.startsWith("P:") ? presets.find((k) => `P:${k.id}` === picked) : undefined;
                          if (own) {
                            editPoint(step, cp.key, fromPreset(own));
                            return;
                          }
                          const kind = picked.slice(2) as CheckpointKind;
                          editPoint(step, cp.key, {
                            kind, kind_name: "",
                            choices: kind === "CHOICE" ? (cp.choices.length ? cp.choices : BLANK_CHOICES()) : [],
                          });
                        }}>
                        <optgroup label="Built in">
                          {BUILT_IN.map((k) => <option key={k.value} value={`K:${k.value}`}>{k.label}</option>)}
                        </optgroup>
                        {presets.length > 0 && (
                          <optgroup label="The lab's own kinds">
                            {presets.map((k) => <option key={k.id} value={`P:${k.id}`}>{k.name}</option>)}
                          </optgroup>
                        )}
                        {cp.kind_name && !preset && (
                          <option value={listed}>{cp.kind_name} (no longer offered)</option>
                        )}
                        <option value="+new">+ New kind…</option>
                      </select>
                      {numeric ? (
                        <>
                          {cp.kind === "PERCENT" ? (
                            <span className="tpl-unit-fixed" aria-label={`Check point ${j + 1} unit`}>%</span>
                          ) : (
                            <input value={cp.unit} maxLength={30} onChange={(e) => editPoint(step, cp.key, { unit: e.target.value })}
                              placeholder="kg" aria-label={`Check point ${j + 1} unit`} />
                          )}
                          <input value={cp.min_value} inputMode="decimal" placeholder="none"
                            onChange={(e) => editPoint(step, cp.key, { min_value: e.target.value })}
                            aria-label={`Check point ${j + 1} lower limit`} />
                          <input value={cp.max_value} inputMode="decimal" placeholder="none"
                            onChange={(e) => editPoint(step, cp.key, { max_value: e.target.value })}
                            aria-label={`Check point ${j + 1} upper limit`} />
                          <select value={cp.decimals} onChange={(e) => editPoint(step, cp.key, { decimals: Number(e.target.value) })}
                            aria-label={`Check point ${j + 1} decimals`}>
                            {[0, 1, 2, 3, 4].map((d) => <option key={d} value={d}>{d}</option>)}
                          </select>
                        </>
                      ) : (
                        <span className="tpl-no-limits">{NO_LIMITS[cp.kind]}</span>
                      )}
                      <span className="tpl-center">
                        <input type="checkbox" checked={cp.required} onChange={(e) => editPoint(step, cp.key, { required: e.target.checked })}
                          aria-label={`Check point ${j + 1} required`} />
                      </span>
                      <RowTools noun="check point" n={j + 1}
                        onUp={j > 0 ? () => editStep(step.key, { checkpoints: swap(step.checkpoints, j, -1) }) : undefined}
                        onDown={j < step.checkpoints.length - 1 ? () => editStep(step.key, { checkpoints: swap(step.checkpoints, j, 1) }) : undefined}
                        onRemove={() => editStep(step.key, { checkpoints: step.checkpoints.filter((c) => c.key !== cp.key) })} />
                    </div>
                    {limit && (
                      <div className={`tpl-limit${limit.wrong ? " wrong" : ""}`}>{limit.text}</div>
                    )}
                    {cp.kind === "CHOICE" && (
                      <div className="tpl-point-options">
                        <span className="cell-sub">
                          Options for “{cp.label || `check point ${j + 1}`}”. An answer not marked acceptable is flagged and needs a reason.
                        </span>
                        <ChoiceOptions value={cp.choices} onChange={(choices) => editPoint(step, cp.key, { choices })}
                          name={cp.label || `Check point ${j + 1}`} />
                      </div>
                    )}
                  </div>
                );
              })}
              <button type="button" className="tpl-add-point"
                onClick={() => editStep(step.key, { checkpoints: [...step.checkpoints, BLANK_POINT()] })}>
                + Add check point
                <span className="cell-sub">Not in the list? Choose <b>+ New kind…</b> at the end of “Kind of value”.</span>
              </button>
            </div>
          </div>
          );
        })}
        <button type="button" className="qcs-add tpl-add-step"
          onClick={() => onSteps([...steps, { key: fresh(), title: "", instructions: "", checkpoints: [BLANK_POINT()] }])}>
          + Add step
        </button>
      </section>

      <section className="tpl-section tpl-signoffs" aria-label={`Stage ${stageNo} sign-off columns`}>
        <div className="tpl-section-head">
          <b>Sign-off columns</b>
          <span className="cell-sub">Signed in this order, each by whoever holds its role; the last acknowledges values out of limit</span>
        </div>
        <div className="tpl-when">
          <span className="tpl-when-label" id={`when-${stageNo}`}>Where they are signed</span>
          <div className="seg" role="group" aria-labelledby={`when-${stageNo}`}>
            <button type="button" className={signEachStep ? "on" : ""} aria-pressed={signEachStep}
              onClick={() => onSignEachStep(true)}>Under every step</button>
            <button type="button" className={signEachStep ? "" : "on"} aria-pressed={!signEachStep}
              onClick={() => onSignEachStep(false)}>Once for the stage</button>
          </div>
          <span className="cell-sub">
            {signEachStep
              ? "Each step gets its own row: the date, then these columns, as on the paper record. A step's values are final once its first column is signed."
              : "One row of signatures at the end of the stage. Every value is final once the first column is signed."}
          </span>
        </div>
        {signoffs.length > 0 && (
          <div className="tpl-signoff tpl-signoff-head" aria-hidden="true">
            <span /><span>Title</span><span>Held by</span><span>Signed by (role)</span><span />
          </div>
        )}
          {signoffs.map((so, i) => (
            <div className="tpl-signoff" key={so.key}>
              <span className="tpl-num" aria-hidden="true">{i + 1}</span>
              <input value={so.title} maxLength={60} onChange={(e) => editSignoff(so.key, { title: e.target.value })}
                placeholder="e.g. Done by" aria-label={`Sign-off ${i + 1} title`} />
              <input value={so.holder} maxLength={60} onChange={(e) => editSignoff(so.key, { holder: e.target.value })}
                placeholder="e.g. Operator" aria-label={`Sign-off ${i + 1} holder`} />
              <select value={so.role_id} onChange={(e) => editSignoff(so.key, { role_id: e.target.value })}
                aria-label={`Sign-off ${i + 1} role`}>
                <option value="">— who signs it? —</option>
                {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
              <RowTools noun="sign-off" n={i + 1}
                onUp={i > 0 ? () => onSignoffs(swap(signoffs, i, -1)) : undefined}
                onDown={i < signoffs.length - 1 ? () => onSignoffs(swap(signoffs, i, 1)) : undefined}
                onRemove={() => onSignoffs(signoffs.filter((s) => s.key !== so.key))} />
            </div>
          ))}
          <div className="actions-bar">
            <button type="button" className="ghost small"
              onClick={() => onSignoffs([...signoffs, { key: fresh(), title: "", holder: "", role_id: "" }])}>
              + Add sign-off column
            </button>
            {signoffs.length === 0 && (
              <button type="button" className="ghost small" onClick={usual}>
                Add Done by → Checked by (Production) → Checked by (QA)
              </button>
            )}
          </div>
      </section>
      {newKindFor && (
        <KindModal
          onSaved={(kind) => {
            onPresetAdded(kind);
            const step = steps.find((st) => st.key === newKindFor.step);
            if (step) editPoint(step, newKindFor.point, fromPreset(kind));
            setNewKindFor(null);
          }}
          onClose={() => setNewKindFor(null)}
        />
      )}
    </div>
  );
}
