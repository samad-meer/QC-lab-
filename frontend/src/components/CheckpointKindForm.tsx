import { useState } from "react";
import { apiPatch, apiPost } from "../api";
import type { CheckpointKind, CheckpointPreset, ChoiceOption } from "../types";
import { Message } from "./Feedback";
import ModalBackdrop from "./ModalBackdrop";
import RowTools from "./RowTools";

/** The built-in kinds a check point, or one of the lab's own kinds, can be. */
export const BUILT_IN: { value: CheckpointKind; label: string; hint: string }[] = [
  { value: "NUMBER", label: "Number", hint: "A measured amount with its unit: kg, L, °C, rpm, minutes, bar…" },
  { value: "PERCENT", label: "Percentage", hint: "LOD, moisture, yield…" },
  { value: "TIME_RANGE", label: "Start and end time", hint: "When a step started and ended" },
  { value: "TIME", label: "Time", hint: "A moment, such as when an addition was made" },
  { value: "DATE", label: "Date", hint: "A day, such as a cleaning or calibration date" },
  { value: "TEXT", label: "Text", hint: "Anything written: an equipment ID, a lot number, an observation" },
  { value: "YES_NO", label: "Yes / No", hint: "A simple confirmation" },
  { value: "CHOICE", label: "Choice from a list", hint: "Options you type, such as Complies / Does not comply" },
  { value: "FILE", label: "Photo or file", hint: "A photo or PDF kept on the record: a balance printout, a label, a chromatogram" },
];

const NUMERIC: CheckpointKind[] = ["NUMBER", "PERCENT"];
export const BLANK_CHOICES = (): ChoiceOption[] => [{ label: "", ok: true }, { label: "", ok: false }];

/**
 * A choice's options, each with whether it is an acceptable answer. An answer not
 * marked acceptable is flagged on the batch record and needs a reason.
 */
export function ChoiceOptions({ value, onChange, name }: {
  value: ChoiceOption[];
  onChange: (next: ChoiceOption[]) => void;
  name: string;
}) {
  const edit = (i: number, patch: Partial<ChoiceOption>) =>
    onChange(value.map((o, n) => (n === i ? { ...o, ...patch } : o)));
  return (
    <div className="choice-options" role="group" aria-label={`${name} options`}>
      {value.map((o, i) => (
        <div className="choice-option" key={i}>
          <input value={o.label} maxLength={100} onChange={(e) => edit(i, { label: e.target.value })}
            placeholder={i === 0 ? "e.g. Complies" : i === 1 ? "e.g. Does not comply" : "Another option"}
            aria-label={`${name} option ${i + 1}`} />
          <label className="choice-ok">
            <input type="checkbox" checked={o.ok} onChange={(e) => edit(i, { ok: e.target.checked })}
              aria-label={`${name} option ${i + 1} acceptable`} />
            Acceptable
          </label>
          <RowTools noun="option" n={i + 1} moves={false} canRemove={value.length > 2}
            onRemove={() => onChange(value.filter((_, n) => n !== i))} />
        </div>
      ))}
      <button type="button" className="link-btn" onClick={() => onChange([...value, { label: "", ok: true }])}>+ Add option</button>
    </div>
  );
}

export interface KindDraft {
  name: string;
  kind: CheckpointKind;
  unit: string;
  decimals: number;
  min_value: string;
  max_value: string;
  choices: ChoiceOption[];
}

/**
 * One of the lab's own kinds of value: a name, what it is based on, and its unit,
 * decimals, limits or options. Saved once, it is offered in every stage.
 */
export function KindModal({ editing, start, onSaved, onClose }: {
  editing?: CheckpointPreset;
  /** A new kind filled in from somewhere, such as a check point a stage already has. */
  start?: Partial<KindDraft>;
  onSaved: (kind: CheckpointPreset) => void;
  onClose: () => void;
}) {
  const [f, setF] = useState<KindDraft>(editing ? {
    name: editing.name, kind: editing.kind, unit: editing.unit, decimals: editing.decimals,
    min_value: editing.min_value ?? "", max_value: editing.max_value ?? "",
    choices: editing.choices.length ? editing.choices : BLANK_CHOICES(),
  } : { name: "", kind: "NUMBER", unit: "", decimals: 2, min_value: "", max_value: "", choices: BLANK_CHOICES(), ...start });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<KindDraft>) => setF((p) => ({ ...p, ...patch }));
  const numeric = NUMERIC.includes(f.kind);

  const save = async () => {
    setBusy(true);
    setError("");
    const body = {
      name: f.name, kind: f.kind, unit: f.kind === "NUMBER" ? f.unit : "", decimals: f.decimals,
      min_value: numeric && f.min_value.trim() ? f.min_value.trim() : null,
      max_value: numeric && f.max_value.trim() ? f.max_value.trim() : null,
      choices: f.kind === "CHOICE" ? f.choices.filter((c) => c.label.trim()) : [],
    };
    try {
      onSaved(editing
        ? await apiPatch<CheckpointPreset>(`/api/checkpoint-kinds/${editing.id}/`, body)
        : await apiPost<CheckpointPreset>("/api/checkpoint-kinds/", body));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the kind.");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3>{editing ? `Change “${editing.name}”` : "A new kind of value"}</h3>
        <p className="modal-sub">
          {editing
            ? "Stages already saved keep the copy they took; this changes what is offered from now on."
            : start
              ? "Filled in from a check point your stages already have. Give it a short name; once saved, it is offered in every stage's list, ready filled in. The stages themselves do not change."
              : "For a value the list does not have. Once saved, it is offered in every stage's list, ready filled in."}
        </p>
        <label className="field">
          Name
          <input value={f.name} maxLength={60} autoFocus onChange={(e) => set({ name: e.target.value })}
            placeholder="e.g. Temperature, Mixer speed, Equipment ID, Visual check" />
        </label>
        <label className="field">
          <span>Based on</span>
          <span className="note">{BUILT_IN.find((k) => k.value === f.kind)?.hint}</span>
          <select value={f.kind} onChange={(e) => set({ kind: e.target.value as CheckpointKind })}>
            {BUILT_IN.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
        </label>
        {numeric && (
          <div className="form-row">
            <label className="field">
              Unit
              <input value={f.kind === "PERCENT" ? "%" : f.unit} maxLength={30} disabled={f.kind === "PERCENT"}
                onChange={(e) => set({ unit: e.target.value })} placeholder="e.g. °C, rpm, min, bar" />
            </label>
            <label className="field">
              Decimals
              <select value={f.decimals} onChange={(e) => set({ decimals: Number(e.target.value) })}>
                {[0, 1, 2, 3, 4].map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
            <label className="field">
              <span>Lower limit <span className="note">(optional)</span></span>
              <input value={f.min_value} inputMode="decimal" onChange={(e) => set({ min_value: e.target.value })} placeholder="e.g. 50" />
            </label>
            <label className="field">
              <span>Upper limit <span className="note">(optional)</span></span>
              <input value={f.max_value} inputMode="decimal" onChange={(e) => set({ max_value: e.target.value })} placeholder="e.g. 80" />
            </label>
          </div>
        )}
        {f.kind === "CHOICE" && (
          <div className="field">
            <span>Options</span>
            <span className="note">An answer not marked acceptable is flagged on the batch record and needs a reason.</span>
            <ChoiceOptions value={f.choices} onChange={(choices) => set({ choices })} name={f.name || "This kind"} />
          </div>
        )}
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="subtle" disabled={busy} onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || !f.name.trim()} onClick={() => void save()}>
            {busy ? "Saving…" : editing ? "Save changes" : "Add this kind"}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}
