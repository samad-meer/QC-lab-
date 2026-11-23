import type { ReactNode } from "react";
import InfoTip from "./InfoTip";

/**
 * A labelled input that can show its own error.
 *
 * Putting the message beside the box it belongs to is the whole point: a
 * single banner saying "3 fields need attention" leaves the user hunting.
 */
export default function Field({
  label,
  error,
  hint,
  info,
  required,
  htmlFor,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  /** A longer explanation behind an "i" beside the label: what the field is for and what to do. */
  info?: ReactNode;
  required?: boolean;
  htmlFor?: string;
  children: ReactNode;
}) {
  return (
    <label className={`field ${error ? "has-error" : ""}`} htmlFor={htmlFor}>
      <span>
        {label} {required && <span className="req" aria-hidden="true">*</span>}
        {info && <InfoTip label={label}>{info}</InfoTip>}
      </span>
      {hint && !error && <span className="note">{hint}</span>}
      {children}
      {error && (
        <span className="field-error" role="alert">
          <span aria-hidden="true">▲</span> {error}
        </span>
      )}
    </label>
  );
}
