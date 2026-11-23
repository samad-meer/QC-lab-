import { useRef, useState } from "react";
import { apiPost, apiUpload } from "../../api";
import { useAuth } from "../../auth";
import type { AttachmentView, BatchDocumentView, Execution, StepView } from "../../types";
import { fmtSize } from "../../util";
import CommentModal from "../CommentModal";
import FilePreview, { canPreview, downloadFile } from "../FilePreview";
import Stamp from "../Stamp";

/** One stored file, wherever it is kept: a step, or a batch. */
export function FileRow({
  a,
  label,
  canReplace,
  canWithdraw,
  onReplace,
  onWithdraw,
}: {
  a: AttachmentView | BatchDocumentView;
  label?: string;
  canReplace: boolean;
  canWithdraw: boolean;
  onReplace: () => void;
  onWithdraw: () => void;
}) {
  const [previewing, setPreviewing] = useState(false);
  const previewable = canPreview(a.extension);

  return (
    <li className={`file-row ${a.is_current ? "" : "old"}`}>
      <span className="file-ext" aria-hidden="true">{a.extension.toUpperCase()}</span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="file-name">
          <a
            href={a.url}
            target="_blank"
            rel="noopener noreferrer"
            className={a.is_current ? "" : "struck"}
            onClick={(e) => {
              if (previewable) {
                e.preventDefault();
                setPreviewing(true);
              }
            }}
          >
            {a.name}
          </a>
          <span className="tag">v{a.version}</span>
          {label && <span className="tag soft">{label}</span>}
          {"attempt" in a && <span className="tag soft">attempt {a.attempt}</span>}
          {!a.is_current && (
            <span className="tag soft">{a.withdrawn_at ? "Withdrawn" : "Replaced"}</span>
          )}
        </div>
        <div className="cell-sub">
          {fmtSize(a.size)} · <Stamp at={a.uploaded_at} by={a.uploaded_by} verb="uploaded by" />
          {" · "}
          <span className="mono" title={`SHA-256 ${a.sha256}`}>sha256 {a.sha256.slice(0, 10)}…</span>
        </div>
        {a.note && <div className="cell-sub">“{a.note}”</div>}
        {a.withdrawn_at && (
          <div className="cell-sub">
            <Stamp at={a.withdrawn_at} by={a.withdrawn_by} verb="withdrawn by" /> — “{a.withdraw_reason}”
          </div>
        )}
      </div>
      <div className="actions-bar">
        {previewable ? (
          <button className="ghost small" onClick={() => setPreviewing(true)}>Preview</button>
        ) : (
          <button className="ghost small" onClick={() => downloadFile(a.url)}>Download</button>
        )}
        {canReplace && <button className="ghost small" onClick={onReplace}>New version</button>}
        {canWithdraw && <button className="danger small" onClick={onWithdraw}>Withdraw…</button>}
      </div>
      {previewing && <FilePreview file={a} onClose={() => setPreviewing(false)} />}
    </li>
  );
}

/**
 * Every file kept against this step, in every attempt. Files are never
 * deleted: a new version replaces one, and a withdrawn one stays listed.
 */
export default function Documents({
  sampleId,
  step,
  userId,
  maxMb,
  onChange,
}: {
  sampleId: number;
  step: StepView;
  userId: number;
  maxMb: number;
  onChange: (e: Execution) => void;
}) {
  const { can } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showOld, setShowOld] = useState(false);
  const [withdrawing, setWithdrawing] = useState<AttachmentView | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const replacing = useRef<AttachmentView | null>(null);

  const labels = new Map(step.checklist.map((r) => [r.item.id, r.item.label]));
  const current = step.attachments.filter((a) => a.is_current);
  const old = step.attachments.filter((a) => !a.is_current);
  const none = current.length === 0 && old.length === 0;

  const upload = async (file: File) => {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("step", step.key);
      if (replacing.current) form.append("replaces_id", String(replacing.current.id));
      onChange(await apiUpload<Execution>(`/api/samples/${sampleId}/attachments/`, form));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
      replacing.current = null;
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const pick = (a: AttachmentView | null) => {
    replacing.current = a;
    fileRef.current?.click();
  };

  return (
    <div>
      <input
        ref={fileRef}
        type="file"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void upload(f);
        }}
      />
      {none ? (
        !step.can.work && <div className="cell-sub">No files yet.</div>
      ) : (
        <ul className="file-list">
          {current.map((a) => (
            <FileRow
              key={a.id}
              a={a}
              label={a.item_id ? labels.get(a.item_id) : undefined}
              canReplace={step.can.work}
              canWithdraw={step.can.work && (a.uploaded_by.id === userId || can("admin.override"))}
              onReplace={() => pick(a)}
              onWithdraw={() => setWithdrawing(a)}
            />
          ))}
        </ul>
      )}
      {old.length > 0 && (
        <>
          <button type="button" className="link-btn" onClick={() => setShowOld((v) => !v)} aria-expanded={showOld}>
            {showOld ? "Hide" : "Show"} {old.length} earlier or withdrawn version{old.length === 1 ? "" : "s"}
          </button>
          {showOld && (
            <ul className="file-list">
              {old.map((a) => (
                <FileRow key={a.id} a={a} label={a.item_id ? labels.get(a.item_id) : undefined}
                  canReplace={false} canWithdraw={false} onReplace={() => {}} onWithdraw={() => {}} />
              ))}
            </ul>
          )}
        </>
      )}
      {error && <div className="field-error" role="alert" style={{ marginTop: 8 }}><span aria-hidden="true">▲</span> {error}</div>}
      {step.can.work && (
        <div className="actions-bar" style={{ marginTop: none ? 0 : 12 }}>
          <button className="ghost small" disabled={busy} onClick={() => pick(null)}>
            {busy ? "Uploading…" : "+ Attach a file"}
          </button>
          <span className="cell-sub">
            {none && "No files yet · "}PDF, images, CSV, text, Excel or Word · up to {maxMb} MB · stored privately
          </span>
        </div>
      )}

      {withdrawing && (
        <CommentModal
          title={`Withdraw ${withdrawing.name}`}
          hint="The file stays on record, marked withdrawn, with your reason. Any checklist answer it supported will need answering again."
          label="Why is it being withdrawn?"
          confirmText="Withdraw the file"
          onConfirm={async (reason) => {
            onChange(await apiPost<Execution>(`/api/attachments/${withdrawing.id}/withdraw/`, { reason }));
            setWithdrawing(null);
          }}
          onClose={() => setWithdrawing(null)}
        />
      )}
    </div>
  );
}
