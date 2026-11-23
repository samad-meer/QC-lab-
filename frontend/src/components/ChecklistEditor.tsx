import type { ChecklistConfig, ResponseType } from "../types";

/** One checklist item while it is being edited. Options are typed as one line. */
export interface ChecklistDraft extends Omit<ChecklistConfig, "id" | "order"> {
  key: number;
  options_text: string;
}

let nextKey = 1;

export const RESPONSE_TYPES: [ResponseType, string][] = [
  ["CHECKBOX", "Tick to confirm"],
  ["YES_NO", "Yes / No"],
  ["PASS_FAIL", "Pass / Fail"],
  ["NUMBER", "Number with limits"],
  ["TEXT", "Text"],
  ["DATE", "Date"],
  ["CHOICE", "Choose from a list"],
  ["FILE", "Document or file"],
];

export function toChecklistDraft(items: ChecklistConfig[]): ChecklistDraft[] {
  return items.map((i) => ({
    key: nextKey++,
    label: i.label,
    help_text: i.help_text,
    response_type: i.response_type,
    required: i.required,
    waivable: i.waivable,
    expected: i.expected,
    unit: i.unit,
    min_value: i.min_value,
    max_value: i.max_value,
    decimals: i.decimals,
    options: i.options,
    options_text: i.options.join(", "),
    file_types: i.file_types,
    max_size_mb: i.max_size_mb,
  }));
}

/** What the server receives — and what "has anything changed?" compares. */
export function checklistPayload(items: ChecklistDraft[]) {
  return items.map((d) => ({
    label: d.label.trim(),
    help_text: d.help_text.trim(),
    response_type: d.response_type,
    required: d.required,
    waivable: d.waivable,
    expected: d.response_type === "YES_NO" || d.response_type === "CHOICE" ? d.expected : "",
    unit: d.response_type === "NUMBER" ? d.unit.trim() : "",
    min_value: d.response_type === "NUMBER" && d.min_value !== null && d.min_value !== "" ? d.min_value : null,
    max_value: d.response_type === "NUMBER" && d.max_value !== null && d.max_value !== "" ? d.max_value : null,
    decimals: d.response_type === "NUMBER" ? d.decimals : null,
    options: d.response_type === "CHOICE"
      ? d.options_text.split(/[,\n]/).map((o) => o.trim()).filter(Boolean)
      : [],
    file_types: d.response_type === "FILE" ? d.file_types : [],
    max_size_mb: d.response_type === "FILE" ? d.max_size_mb : 10,
  }));
}

function blank(): ChecklistDraft {
  return {
    key: nextKey++, label: "", help_text: "", response_type: "CHECKBOX", required: true, waivable: false,
    expected: "", unit: "", min_value: null, max_value: null, decimals: null, options: [], options_text: "",
    file_types: [], max_size_mb: 10,
  };
}

/**
 * A step's checklist: the checks and documents it needs before it can be
 * signed. The server re-validates everything and decides every answer.
 */
export default function ChecklistEditor({
  items,
  onChange,
  fileTypes,
  maxMb,
}: {
  items: ChecklistDraft[];
  onChange: (items: ChecklistDraft[]) => void;
  fileTypes: string[];
  maxMb: number;
}) {
  const edit = (key: number, patch: Partial<ChecklistDraft>) =>
    onChange(items.map((d) => (d.key === key ? { ...d, ...patch } : d)));
  const move = (index: number, by: number) => {
    const next = [...items];
    const [row] = next.splice(index, 1);
    next.splice(index + by, 0, row);
    onChange(next);
  };

  return (
    <div className="cl-editor">
      {items.length === 0 && (
        <div className="cell-sub">No checks yet — this step needs only its signature.</div>
      )}
      {items.map((d, i) => {
        const options = d.options_text.split(/[,\n]/).map((o) => o.trim()).filter(Boolean);
        return (
          <div key={d.key} className="cl-item">
            <div className="cl-row">
              <span className="cl-num" aria-hidden="true">{i + 1}</span>
              <input
                value={d.label}
                onChange={(e) => edit(d.key, { label: e.target.value })}
                placeholder="e.g. Balance calibration checked today"
                maxLength={200}
                aria-label={`Check ${i + 1}`}
                style={{ flex: 2, minWidth: 180 }}
              />
              <select
                value={d.response_type}
                onChange={(e) => edit(d.key, { response_type: e.target.value as ResponseType, expected: "" })}
                aria-label={`Answer type for check ${i + 1}`}
                style={{ flex: 1, minWidth: 180 }}
              >
                {RESPONSE_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
              </select>
              <label className="cl-flag">
                <input type="checkbox" checked={d.required} onChange={(e) => edit(d.key, { required: e.target.checked })} />
                Required
              </label>
              <label className="cl-flag" title="Someone with “Waive a stage requirement” may set it aside, with a reason">
                <input type="checkbox" checked={d.waivable} onChange={(e) => edit(d.key, { waivable: e.target.checked })} />
                Waivable
              </label>
              <span className="cl-tools">
                <button type="button" className="icon-btn" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up" title="Move up">↑</button>
                <button type="button" className="icon-btn" disabled={i === items.length - 1} onClick={() => move(i, 1)} aria-label="Move down" title="Move down">↓</button>
                <button type="button" className="icon-btn danger" onClick={() => onChange(items.filter((x) => x.key !== d.key))} aria-label="Remove check" title="Remove">✕</button>
              </span>
            </div>

            <div className="cl-row cl-detail">
              {d.response_type === "YES_NO" && (
                <label className="cl-field">
                  Conforming answer
                  <select value={d.expected} onChange={(e) => edit(d.key, { expected: e.target.value })}>
                    <option value="">Either answer</option>
                    <option value="YES">Yes</option>
                    <option value="NO">No</option>
                  </select>
                </label>
              )}
              {d.response_type === "NUMBER" && (
                <>
                  <label className="cl-field">Unit<input className="short" value={d.unit} onChange={(e) => edit(d.key, { unit: e.target.value })} placeholder="°C" /></label>
                  <label className="cl-field">Minimum<input className="short" inputMode="decimal" value={d.min_value ?? ""} onChange={(e) => edit(d.key, { min_value: e.target.value })} placeholder="none" /></label>
                  <label className="cl-field">Maximum<input className="short" inputMode="decimal" value={d.max_value ?? ""} onChange={(e) => edit(d.key, { max_value: e.target.value })} placeholder="none" /></label>
                  <label className="cl-field">Decimals
                    <select value={d.decimals ?? ""} onChange={(e) => edit(d.key, { decimals: e.target.value === "" ? null : Number(e.target.value) })}>
                      <option value="">As entered</option>
                      {[0, 1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </label>
                </>
              )}
              {d.response_type === "CHOICE" && (
                <>
                  <label className="cl-field" style={{ flex: 2, minWidth: 220 }}>
                    Answers, separated by commas
                    <input value={d.options_text} onChange={(e) => edit(d.key, { options_text: e.target.value })} placeholder="Clear, Slightly turbid, Turbid" />
                  </label>
                  <label className="cl-field">
                    Conforming answer
                    <select value={d.expected} onChange={(e) => edit(d.key, { expected: e.target.value })}>
                      <option value="">Any answer</option>
                      {options.map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  </label>
                </>
              )}
              {d.response_type === "FILE" && (
                <>
                  <fieldset className="cl-field cl-types">
                    <legend>Accepted types <span className="note">(none ticked = any the lab accepts)</span></legend>
                    {fileTypes.map((t) => (
                      <label key={t} className="cl-flag">
                        <input
                          type="checkbox"
                          checked={d.file_types.includes(t)}
                          onChange={(e) => edit(d.key, {
                            file_types: e.target.checked ? [...d.file_types, t] : d.file_types.filter((x) => x !== t),
                          })}
                        />
                        .{t}
                      </label>
                    ))}
                  </fieldset>
                  <label className="cl-field">Largest file (MB)
                    <input className="short" type="number" min={1} max={maxMb} value={d.max_size_mb}
                      onChange={(e) => edit(d.key, { max_size_mb: Number(e.target.value) || 1 })} />
                  </label>
                </>
              )}
              {d.response_type === "PASS_FAIL" && <span className="cell-sub">Only “Pass” conforms.</span>}
              <label className="cl-field" style={{ flex: 2, minWidth: 220 }}>
                Guidance (optional)
                <input value={d.help_text} onChange={(e) => edit(d.key, { help_text: e.target.value })} maxLength={300}
                  placeholder="What to check, and how" />
              </label>
            </div>
          </div>
        );
      })}
      <button type="button" className="ghost small" onClick={() => onChange([...items, blank()])} disabled={items.length >= 30}>
        + Add a check or document
      </button>
    </div>
  );
}
