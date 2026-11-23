import { useRef, useState } from "react";
import { apiPost, apiUpload } from "../../api";
import type { AttachmentView, ChecklistRow, Execution, StepView } from "../../types";
import CommentModal from "../CommentModal";
import Stamp from "../Stamp";

const TYPE_LABEL: Record<string, string> = {
  CHECKBOX: "Tick to confirm",
  YES_NO: "Yes / No",
  PASS_FAIL: "Pass / Fail",
  NUMBER: "Number",
  TEXT: "Text",
  DATE: "Date",
  CHOICE: "From a list",
  FILE: "Document",
};

/**
 * One check or required document. The server decides whether an answer
 * meets the requirement; a changed answer keeps the earlier one on record.
 */
export default function ChecklistRowView({
  sampleId,
  step,
  row,
  attachments,
  onChange,
}: {
  sampleId: number;
  step: StepView;
  row: ChecklistRow;
  attachments: AttachmentView[];
  onChange: (e: Execution) => void;
}) {
  const { item, response, history, waiver } = row;
  const editable = step.can.work;
  const [draft, setDraft] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [clearing, setClearing] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const send = async (value: unknown, extra: Record<string, unknown> = {}) => {
    setBusy(true);
    setError("");
    try {
      onChange(
        await apiPost<Execution>(`/api/samples/${sampleId}/checklist/`, {
          item_id: item.id, value, reason, ...extra,
        }),
      );
      setDraft("");
      setReason("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  };

  const upload = async (file: File) => {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("step", step.key);
      form.append("item_id", String(item.id));
      onChange(await apiUpload<Execution>(`/api/samples/${sampleId}/attachments/`, form));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  // A document uploaded for this item in an earlier attempt can be used again.
  const reusable =
    item.response_type === "FILE" && !response
      ? attachments.find((a) => a.item_id === item.id && a.is_current)
      : undefined;
  const file = response?.attachment_id ? attachments.find((a) => a.id === response.attachment_id) : undefined;

  const choice = (options: [string, string][]) => (
    <div className="seg" role="group" aria-label={item.label}>
      {options.map(([value, label]) => (
        <button
          key={value}
          type="button"
          className={response?.value === value ? "on" : ""}
          aria-pressed={response?.value === value}
          disabled={busy}
          onClick={() => response?.value !== value && void send(value)}
        >
          {label}
        </button>
      ))}
    </div>
  );

  const input = () => {
    switch (item.response_type) {
      case "CHECKBOX":
        return response ? null : (
          <button type="button" className="ghost small" disabled={busy} onClick={() => void send(true)}>
            ☐ Tick to confirm
          </button>
        );
      case "YES_NO":
        return choice([["YES", "Yes"], ["NO", "No"]]);
      case "PASS_FAIL":
        return choice([["PASS", "Pass"], ["FAIL", "Fail"]]);
      case "CHOICE":
        return (
          <select
            value={response?.value ?? ""}
            disabled={busy}
            onChange={(e) => e.target.value && void send(e.target.value)}
            aria-label={item.label}
            style={{ maxWidth: 260 }}
          >
            <option value="">— choose —</option>
            {item.options.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        );
      case "FILE":
        return (
          <>
            <input
              ref={fileRef}
              type="file"
              hidden
              accept={(item.file_types.length ? item.file_types : []).map((t) => `.${t}`).join(",") || undefined}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void upload(f);
              }}
            />
            <button type="button" className="ghost small" disabled={busy} onClick={() => fileRef.current?.click()}>
              {busy ? "Uploading…" : response ? "Upload a new version" : "Upload"}
            </button>
            {reusable && (
              <button
                type="button"
                className="subtle small"
                disabled={busy}
                onClick={() => void send(null, { attachment_id: reusable.id })}
              >
                Use {reusable.name} (v{reusable.version}) again
              </button>
            )}
          </>
        );
      default: {
        const type = item.response_type === "DATE" ? "date" : "text";
        return (
          <>
            <input
              type={type}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              inputMode={item.response_type === "NUMBER" ? "decimal" : undefined}
              placeholder={
                item.response_type === "NUMBER" ? `number${item.unit ? ` (${item.unit})` : ""}` : "Your answer"
              }
              className={item.response_type === "NUMBER" ? "short" : ""}
              style={item.response_type === "TEXT" ? { minWidth: 220, flex: 1 } : undefined}
              aria-label={item.label}
            />
            <button type="button" className="ghost small" disabled={busy || !draft.trim()} onClick={() => void send(draft)}>
              {busy ? "Saving…" : response ? "Change" : "Save"}
            </button>
          </>
        );
      }
    }
  };

  return (
    <div className={`check-row ${response ? (response.conforms ? "ok" : "bad") : waiver ? "waived" : ""}`}>
      <div className="check-mark" aria-hidden="true">
        {waiver ? "≈" : response ? (response.conforms ? "✓" : "!") : item.required ? "○" : "·"}
      </div>
      <div className="check-main">
        <div className="check-label">
          <b>{item.label}</b>
          <span className="check-tags">
            <span className="tag">{TYPE_LABEL[item.response_type]}</span>
            {item.required ? <span className="tag">Required</span> : <span className="tag soft">Optional</span>}
            {item.waivable && <span className="tag soft">Waivable</span>}
            {item.requirement && <span className="tag req">Must be {item.requirement}</span>}
          </span>
        </div>
        {item.help_text && <div className="check-help">{item.help_text}</div>}

        {response && (
          <div className="check-answer">
            <span className={`badge ${response.conforms ? "pass" : "fail"}`}>
              {file ? (
                <a href={file.url} target="_blank" rel="noopener noreferrer">{response.display} · v{file.version}</a>
              ) : (
                response.display
              )}
            </span>
            {!response.conforms && <span className="check-note">Does not meet the requirement</span>}
            <Stamp at={response.answered_at} by={response.answered_by} />
            {editable && item.response_type !== "FILE" && (
              <button type="button" className="link-btn" onClick={() => setClearing(true)}>Clear…</button>
            )}
          </div>
        )}
        {waiver && (
          <div className="check-answer">
            <span className="badge warn">Waived</span>
            <span className="check-note">“{waiver.reason}”</span>
            <Stamp at={waiver.at} by={waiver.by} />
          </div>
        )}

        {editable && !waiver && (
          <div className="check-input">
            {input()}
            {response && (
              ["YES_NO", "PASS_FAIL", "CHOICE"].includes(item.response_type) ||
              (["NUMBER", "TEXT", "DATE"].includes(item.response_type) && draft.trim() !== "")
            ) && (
              <input
                className="reason-input"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Reason for changing the answer (kept with the history)"
                aria-label={`Reason for changing ${item.label}`}
              />
            )}
          </div>
        )}
        {error && <div className="field-error" role="alert"><span aria-hidden="true">▲</span> {error}</div>}

        {history.length > 0 && (
          <div className="check-history">
            <button type="button" className="link-btn" onClick={() => setShowHistory((v) => !v)} aria-expanded={showHistory}>
              {showHistory ? "Hide" : "Show"} {history.length} earlier answer{history.length === 1 ? "" : "s"}
            </button>
            {showHistory && (
              <ul>
                {history.map((h) => (
                  <li key={h.id}>
                    <span className="struck">{h.display}</span>{" "}
                    <span className="cell-sub">
                      attempt {h.attempt} · <Stamp at={h.answered_at} by={h.answered_by} verb="answered by" /> ·{" "}
                      <Stamp at={h.replaced_at} by={h.replaced_by} verb="replaced by" />
                      {h.change_reason && <> — “{h.change_reason}”</>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {clearing && (
        <CommentModal
          title={`Clear “${item.label}”`}
          hint="The answer stays on record, marked as cleared, with your reason."
          label="Why is the answer being cleared?"
          confirmText="Clear the answer"
          onConfirm={async (why) => {
            onChange(await apiPost<Execution>(`/api/samples/${sampleId}/checklist/`, {
              item_id: item.id, clear: true, reason: why,
            }));
            setClearing(false);
          }}
          onClose={() => setClearing(false)}
        />
      )}
    </div>
  );
}
