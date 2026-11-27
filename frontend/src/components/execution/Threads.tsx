import { useState } from "react";
import { apiPost } from "../../api";
import type { CommentView, Execution } from "../../types";
import { initials } from "../SignatureGrid";
import Stamp from "../Stamp";

function Composer({
  initial = "",
  withKind,
  autoFocus,
  submitText,
  onSubmit,
  onCancel,
}: {
  initial?: string;
  withKind?: boolean;
  autoFocus?: boolean;
  submitText: string;
  onSubmit: (body: string, kind: "NOTE" | "FEEDBACK") => Promise<void>;
  onCancel?: () => void;
}) {
  const [body, setBody] = useState(initial);
  const [kind, setKind] = useState<"NOTE" | "FEEDBACK">("NOTE");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await onSubmit(body, kind);
      setBody("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not post.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="composer">
      <textarea
        rows={2}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Write a note — it is kept on the record and cannot be deleted."
        maxLength={4000}
        aria-label={submitText}
        autoFocus={autoFocus}
      />
      <div className="actions-bar">
        {withKind && (
          <select value={kind} onChange={(e) => setKind(e.target.value as "NOTE" | "FEEDBACK")} aria-label="Kind" style={{ width: "auto" }}>
            <option value="NOTE">Note</option>
            <option value="FEEDBACK">Review feedback</option>
          </select>
        )}
        <div className="spacer" />
        {onCancel && <button type="button" className="subtle small" onClick={onCancel} disabled={busy}>Cancel</button>}
        <button type="button" className="primary small" disabled={busy || !body.trim() || body === initial} onClick={() => void submit()}>
          {busy ? "Posting…" : submitText}
        </button>
      </div>
      {error && <div className="field-error" role="alert"><span aria-hidden="true">▲</span> {error}</div>}
    </div>
  );
}

function Comment({
  c,
  userId,
  canComment,
  post,
  depth,
}: {
  c: CommentView;
  userId: number;
  canComment: boolean;
  post: (data: Record<string, unknown>) => Promise<void>;
  depth: number;
}) {
  const [mode, setMode] = useState<"reply" | "amend" | null>(null);
  const [showVersions, setShowVersions] = useState(false);

  return (
    <li className={`comment ${c.kind === "FEEDBACK" ? "feedback" : ""}`}>
      <span className="comment-avatar" aria-hidden="true">{initials(c.author.name)}</span>
      <div className="comment-body">
        <div className="comment-meta">
          <Stamp at={c.created_at} by={c.author} />
          {c.kind === "FEEDBACK" && <span className="badge hot">Review feedback</span>}
          {c.amended_at && <span className="tag soft">Amended <Stamp at={c.amended_at} /></span>}
        </div>
        <div className="comment-text">{c.body}</div>
        <div className="comment-actions">
          {canComment && depth === 0 && <button type="button" className="link-btn" onClick={() => setMode("reply")}>Reply</button>}
          {canComment && c.author.id === userId && <button type="button" className="link-btn" onClick={() => setMode("amend")}>Amend</button>}
          {c.versions.length > 0 && (
            <button type="button" className="link-btn" onClick={() => setShowVersions((v) => !v)} aria-expanded={showVersions}>
              {showVersions ? "Hide" : "Show"} {c.versions.length - 1} earlier wording{c.versions.length > 2 ? "s" : ""}
            </button>
          )}
        </div>
        {showVersions && (
          <ol className="comment-versions">
            {c.versions.slice(0, -1).map((v) => (
              <li key={v.id}><span className="struck">{v.body}</span> <span className="cell-sub"><Stamp at={v.at} /></span></li>
            ))}
          </ol>
        )}
        {mode && (
          <Composer
            autoFocus
            initial={mode === "amend" ? c.body : ""}
            submitText={mode === "amend" ? "Save amendment" : "Reply"}
            onCancel={() => setMode(null)}
            onSubmit={async (body) => {
              await post(mode === "amend" ? { amends_id: c.latest_id, body } : { parent_id: c.id, body });
              setMode(null);
            }}
          />
        )}
        {c.replies.length > 0 && (
          <ul className="comment-list nested">
            {c.replies.map((r) => <Comment key={r.id} c={r} userId={userId} canComment={canComment} post={post} depth={depth + 1} />)}
          </ul>
        )}
      </div>
    </li>
  );
}

/**
 * Notes and review feedback for a step. Nothing is edited or deleted: an
 * amendment is a new wording with the earlier ones kept beneath it. The box
 * for a new note opens from its button, so a step with nothing to say stays short.
 */
export default function Threads({
  sampleId,
  stepKey,
  comments,
  userId,
  canComment,
  writing,
  onWriting,
  onChange,
}: {
  sampleId: number;
  stepKey: string;
  comments: CommentView[];
  userId: number;
  canComment: boolean;
  writing: boolean;
  onWriting: (open: boolean) => void;
  onChange: (e: Execution) => void;
}) {
  const post = async (data: Record<string, unknown>) => {
    onChange(await apiPost<Execution>(`/api/samples/${sampleId}/comments/`, { step: stepKey, ...data }));
  };

  return (
    <div>
      {comments.length > 0 && (
        <ul className="comment-list">
          {comments.map((c) => <Comment key={c.id} c={c} userId={userId} canComment={canComment} post={post} depth={0} />)}
        </ul>
      )}
      {canComment ? (
        writing ? (
          <Composer withKind autoFocus submitText="Post" onCancel={() => onWriting(false)}
            onSubmit={async (body, kind) => {
              await post({ body, kind });
              onWriting(false);
            }} />
        ) : (
          <button type="button" className="ghost small note-add" onClick={() => onWriting(true)}>+ Add a note</button>
        )
      ) : (
        <div className="cell-sub" style={{ marginTop: 10 }}>You can read these notes. Your role cannot add to them.</div>
      )}
    </div>
  );
}
