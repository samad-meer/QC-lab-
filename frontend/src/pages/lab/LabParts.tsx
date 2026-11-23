import { useState } from "react";
import { Link } from "react-router-dom";
import CommentModal from "../../components/CommentModal";
import SignModal from "../../components/SignModal";
import type { LabAction, LabCell, LabColumn, LabField, LabValue } from "../../types";
import { fmtDate, fmtDateTime, nowLocalInput } from "../../util";

export type Values = Record<string, string>;

function written(value: LabValue | undefined, kind: LabColumn["kind"]): string {
  if (value === null || value === undefined || value === "") return "—";
  if (kind === "date") return fmtDate(String(value));
  if (kind === "datetime") return fmtDateTime(String(value));
  return String(value);
}

/** One value as the server sent it: a badge, a link and a second line where it says so. */
export function LabCellView({ cell, kind = "" }: { cell: LabCell | undefined; kind?: LabColumn["kind"] }) {
  if (cell === null || cell === undefined || typeof cell !== "object") return <>{written(cell, kind)}</>;
  const text = written(cell.text, kind);
  const body = cell.tone ? <span className={`badge ${cell.tone}`}>{text}</span> : text;
  return (
    <>
      {cell.to ? <Link to={cell.to} onClick={(e) => e.stopPropagation()}>{body}</Link> : body}
      {cell.sub && <div className="cell-sub">{cell.sub}</div>}
    </>
  );
}

export function initialValues(fields: LabField[]): Values {
  const values: Values = {};
  for (const field of fields) {
    values[field.key] = field.initial == null ? (field.kind === "datetime" ? nowLocalInput() : "") : String(field.initial);
  }
  return values;
}

export function FieldInput({ field, value, onChange }: {
  field: LabField;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span>
        {field.label}
        {field.required && <span className="req"> *</span>}
        {field.note && <span className="note"> {field.note}</span>}
      </span>
      {field.kind === "select" ? (
        <select required={field.required} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">{field.required ? "Choose" : "None"}</option>
          {field.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      ) : field.kind === "textarea" ? (
        <textarea required={field.required} rows={3} value={value} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input
          required={field.required}
          type={field.kind === "datetime" ? "datetime-local" : field.kind === "date" ? "date"
            : field.kind === "password" ? "password" : "text"}
          inputMode={field.kind === "number" ? "decimal" : undefined}
          autoComplete={field.kind === "password" ? "current-password" : undefined}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </label>
  );
}

/** A form's fields: the short ones side by side, as many as fit, and long text under them. */
export function FieldGrid({ fields, values, onChange }: {
  fields: LabField[];
  values: Values;
  onChange: (key: string, value: string) => void;
}) {
  const short = fields.filter((f) => f.kind !== "textarea");
  const long = fields.filter((f) => f.kind === "textarea");
  return (
    <>
      {short.length > 0 && (
        <div className="report-filters">
          {short.map((f) => (
            <FieldInput key={f.key} field={f} value={values[f.key] ?? ""} onChange={(v) => onChange(f.key, v)} />
          ))}
        </div>
      )}
      {long.map((f) => (
        <FieldInput key={f.key} field={f} value={values[f.key] ?? ""} onChange={(v) => onChange(f.key, v)} />
      ))}
    </>
  );
}

/** One action on a record, as the server describes it. A bare signature is the signing dialog. */
export function ActionDialog({ action, onSend, onClose }: {
  action: LabAction;
  onSend: (body: Record<string, unknown>) => Promise<void>;
  onClose: () => void;
}) {
  const [values, setValues] = useState(() => initialValues(action.fields));
  const [password, setPassword] = useState("");

  if (action.signed && !action.comment && action.fields.length === 0) {
    return (
      <SignModal
        title={action.title}
        meaning={action.meaning}
        description={action.hint}
        onConfirm={(signature) => onSend({ password: signature, digest: action.digest })}
        onClose={onClose}
      />
    );
  }
  return (
    <CommentModal
      title={action.title}
      hint={action.hint}
      label={action.comment}
      optional={!action.comment_required}
      confirmText={action.label.replace("…", "")}
      tone={action.tone}
      onConfirm={(comment) => onSend({
        ...values, comment,
        ...(action.signed ? { password } : {}),
        ...(action.digest ? { digest: action.digest } : {}),
      })}
      onClose={onClose}
    >
      <FieldGrid fields={action.fields} values={values} onChange={(key, value) => setValues((v) => ({ ...v, [key]: value }))} />
      {action.signed && (
        <label className="field">
          Your password <span className="note">this is a signature</span>
          <input type="password" required autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)} />
        </label>
      )}
    </CommentModal>
  );
}
