import { Link } from "react-router-dom";
import { useAuth } from "../../auth";
import type { RawData, ResultOptions } from "../../types";
import InfoTip from "../InfoTip";

export interface RawDraft {
  worksheet_ref: string;
  instrument_id: string;
  material_ids: number[];
  notes: string;
  readings: { label: string; value: string }[];
}

export const BLANK_RAW: RawDraft = { worksheet_ref: "", instrument_id: "", material_ids: [], notes: "", readings: [] };

const filled = (raw: RawDraft) => raw.readings.filter((r) => r.value.trim() !== "");

export const hasReadings = (raw: RawDraft) => filled(raw).length > 0;

/** Only what was filled in, so a result with none of it is sent as it always was. */
export function rawBody(raw: RawDraft): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (raw.worksheet_ref.trim()) body.worksheet_ref = raw.worksheet_ref;
  if (raw.instrument_id) body.instrument_id = raw.instrument_id;
  if (raw.material_ids.length > 0) body.material_ids = raw.material_ids;
  if (raw.notes.trim()) body.notes = raw.notes;
  if (hasReadings(raw)) body.readings = filled(raw);
  return body;
}

/** The expandable part of an entry row. Instruments and lots that cannot be used are not offered. */
export default function RawDataFields({ raw, options, numeric, onChange }: {
  raw: RawDraft;
  options: ResultOptions | null;
  /** An observation takes no readings. */
  numeric: boolean;
  onChange: (next: RawDraft) => void;
}) {
  const set = (patch: Partial<RawDraft>) => onChange({ ...raw, ...patch });
  const { can } = useAuth();
  // Where to add a missing one: a link for whoever can open that register, the words for everyone else.
  const place = (to: string, see: "instrument.view" | "material.view", words: string) =>
    can(see) ? <Link to={to}>{words}</Link> : <b>{words}</b>;
  const setReading = (at: number, patch: Partial<RawDraft["readings"][number]>) =>
    set({ readings: raw.readings.map((r, i) => (i === at ? { ...r, ...patch } : r)) });
  const toggle = (id: number, on: boolean) =>
    set({ material_ids: on ? [...raw.material_ids, id] : raw.material_ids.filter((m) => m !== id) });

  return (
    <details className="more-fields" style={{ flexBasis: "100%", minWidth: 250 }}>
      <summary>
        Raw data
        <InfoTip label="Raw data">
          <p>Optional. What this result was worked out from: the worksheet, the instrument, the materials and the
            individual readings.</p>
          <p>It is saved with the result, shown to the reviewers and kept in the sample's history.</p>
        </InfoTip>
      </summary>
      <div className="doc-parts" style={{ marginTop: 10, gap: 12 }}>
        <div className="report-filters">
          <label className="field">
            <span>
              Worksheet reference
              <InfoTip label="Worksheet reference">
                <p>The page or number of the worksheet, notebook or printout this test was worked on, so the result
                  can be traced back to it.</p>
              </InfoTip>
            </span>
            <input maxLength={100} value={raw.worksheet_ref} onChange={(e) => set({ worksheet_ref: e.target.value })} />
          </label>
          <label className="field">
            <span>
              Instrument
              <InfoTip label="Instrument">
                <p>The instrument this test was run on. Leave it on <b>None</b> if no instrument was used.</p>
                <p>Only instruments that are <b>in service</b> and have a <b>passing calibration that is not
                  overdue</b> are listed, so a result is never tied to an instrument that cannot be relied on.</p>
                <p>Missing one? Someone who manages instruments (by default a checker, lab head or administrator):</p>
                <ol>
                  <li>opens {place("/lab/instruments", "instrument.view", "Lab records → Instruments")} and adds it,</li>
                  <li>records a calibration that passed, with its next due date.</li>
                </ol>
              </InfoTip>
            </span>
            {options && options.instruments.length === 0 && <span className="note">No instrument is ready to use yet</span>}
            <select value={raw.instrument_id} onChange={(e) => set({ instrument_id: e.target.value })}>
              <option value="">None</option>
              {options?.instruments.map((i) => <option key={i.id} value={i.id}>{i.code} — {i.name}</option>)}
            </select>
          </label>
        </div>
        {options && (
          <fieldset className="rule-roles">
            <legend>
              Materials used
              <InfoTip label="Materials used">
                <p>The reference standards, reagents, columns and consumables used for this test. Tick each lot
                  you used.</p>
                <p>Only lots that are <b>available</b> and <b>not past their expiry</b> are listed.</p>
                <p>Missing one? Someone who manages standards and reagents (by default a checker, lab head or
                  administrator) adds the lot under {place("/lab/materials", "material.view", "Lab records → Standards and reagents")}.</p>
              </InfoTip>
            </legend>
            {options.materials.length === 0 && <span className="cell-sub">No standard or reagent lot is available yet</span>}
            {options.materials.map((m) => (
              <label className="cl-flag" key={m.id}>
                <input type="checkbox" checked={raw.material_ids.includes(m.id)}
                  onChange={(e) => toggle(m.id, e.target.checked)} />
                {m.code} lot {m.lot}
              </label>
            ))}
          </fieldset>
        )}
        {numeric && (
          <div className="doc-parts" style={{ gap: 8 }}>
            {raw.readings.map((r, i) => (
              <div className="entry-cell" key={i}>
                <input aria-label={`Name of reading ${i + 1}`} style={{ flex: "1 1 120px" }} maxLength={60} value={r.label}
                  onChange={(e) => setReading(i, { label: e.target.value })} />
                <input aria-label={`Value of reading ${i + 1}`} className="short" inputMode="decimal" placeholder="value" value={r.value}
                  onChange={(e) => setReading(i, { value: e.target.value })} />
                <button type="button" className="icon-btn danger" aria-label={`Remove reading ${i + 1}`}
                  onClick={() => set({ readings: raw.readings.filter((_, n) => n !== i) })}>✕</button>
              </div>
            ))}
            <div className="entry-cell">
              <button type="button" className="ghost small"
                onClick={() => set({ readings: [...raw.readings, { label: `Replicate ${raw.readings.length + 1}`, value: "" }] })}>
                + Add a reading
              </button>
              <span className="cell-sub">With no result typed in, the server reports their mean.</span>
            </div>
          </div>
        )}
        <label className="field">
          <span>
            Notes
            <InfoTip label="Notes">
              <p>Anything a reviewer should know about how this test was done, for example which preparation was
                used or why a reading was repeated. Saved with the result and shown to the reviewers.</p>
            </InfoTip>
          </span>
          <input maxLength={1000} value={raw.notes} onChange={(e) => set({ notes: e.target.value })} />
        </label>
      </div>
    </details>
  );
}

/** What was recorded behind a result. Nothing is drawn for a result with none. */
export function RawDataView({ raw }: { raw: RawData | null }) {
  if (!raw) return null;
  return (
    <details className="cl-details">
      <summary>Raw data</summary>
      {raw.worksheet_ref && <div className="cell-sub">Worksheet {raw.worksheet_ref}</div>}
      {raw.instrument && <div className="cell-sub">Instrument {raw.instrument.code} — {raw.instrument.name}</div>}
      {raw.materials.map((m) => <div className="cell-sub" key={m.id}>{m.kind}: {m.code} lot {m.lot}</div>)}
      {raw.readings.map((r, i) => <div className="cell-sub" key={i}>{r.label}: <span className="mono">{r.value}</span></div>)}
      {raw.mean && <div className="cell-sub">Mean: <span className="mono">{raw.mean}</span></div>}
      {raw.notes && <div className="cell-sub">“{raw.notes}”</div>}
    </details>
  );
}
