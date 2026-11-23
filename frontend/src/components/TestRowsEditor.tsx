import type { LimitKind, MethodChoice, TestDraft } from "../types";

export const BLANK_TEST: TestDraft = {
  name: "", method: "", unit: "", limit_type: "NUMERIC_RANGE", min_value: "", max_value: "", decimals: 2,
  text_expected: "", limit_text: "",
};

/** One test's fields. The same editor serves a specification's tests and the template library. */
export function TestFields({
  test,
  limitTypes,
  methods,
  onChange,
}: {
  test: TestDraft;
  limitTypes: LimitKind[];
  /** The method master, for a test in a specification. A template names no method record. */
  methods?: MethodChoice[];
  onChange: (patch: Partial<TestDraft>) => void;
}) {
  const kind = test.limit_type;
  const numeric = kind === "NUMERIC_RANGE" || kind === "NUMERIC_MIN" || kind === "NUMERIC_MAX";
  return (
    <div className="test-fields">
      <label className="field">Test name
        <input value={test.name} onChange={(e) => onChange({ name: e.target.value })} placeholder="e.g. Assay (Paracetamol)" />
      </label>
      <label className="field">Method
        <input value={test.method} onChange={(e) => onChange({ method: e.target.value })} placeholder="e.g. USP, HPLC" />
      </label>
      {methods && (
        <label className="field">Method record
          <select value={test.method_record_id ?? ""}
            onChange={(e) => onChange({ method_record_id: e.target.value ? Number(e.target.value) : null })}>
            <option value="">None</option>
            {/* A retired method stays selectable here so a copied draft shows what it names. */}
            {test.method_record_id != null && !methods.some((m) => m.id === test.method_record_id) && (
              <option value={test.method_record_id}>{test.method_record_label || "A retired method"}</option>
            )}
            {methods.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}{m.status === "EFFECTIVE" ? "" : ` (${m.status_label.toLowerCase()})`}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="field">Limit
        <select value={kind} onChange={(e) => onChange({ limit_type: e.target.value, limit_text: "" })}>
          {limitTypes.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
        </select>
      </label>
      {numeric && (
        <label className="field">Unit
          <input value={test.unit} onChange={(e) => onChange({ unit: e.target.value, limit_text: "" })} placeholder="%" />
        </label>
      )}
      {(kind === "NUMERIC_RANGE" || kind === "NUMERIC_MIN") && (
        <label className="field">Minimum
          <input inputMode="decimal" value={test.min_value ?? ""} onChange={(e) => onChange({ min_value: e.target.value, limit_text: "" })} />
        </label>
      )}
      {(kind === "NUMERIC_RANGE" || kind === "NUMERIC_MAX") && (
        <label className="field">Maximum
          <input inputMode="decimal" value={test.max_value ?? ""} onChange={(e) => onChange({ max_value: e.target.value, limit_text: "" })} />
        </label>
      )}
      {numeric && (
        <label className="field">Decimals
          <select value={test.decimals} onChange={(e) => onChange({ decimals: Number(e.target.value), limit_text: "" })}>
            {[0, 1, 2, 3, 4, 5, 6].map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
      )}
      {kind === "TEXT_COMPLIES" && (
        <label className="field">Result must read
          <input value={test.text_expected} onChange={(e) => onChange({ text_expected: e.target.value })} placeholder="e.g. Complies" />
        </label>
      )}
      <label className="field">Limit as printed
        <input value={test.limit_text} onChange={(e) => onChange({ limit_text: e.target.value })}
          placeholder="Blank = written from the limit" />
      </label>
    </div>
  );
}
