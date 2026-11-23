import { useCallback, useEffect, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "../api";
import { useAuth } from "../auth";
import type { MethodChoice, SpecVersion, SpecificationsResponse, TestDraft } from "../types";
import { fmtDate, fmtDateTime } from "../util";
import CommentModal from "./CommentModal";
import { EmptyState, Message, TableSkeleton } from "./Feedback";
import SignModal from "./SignModal";
import { BLANK_TEST, TestFields } from "./TestRowsEditor";
import { useToast } from "./Toast";
import UnsavedChangesGuard from "./UnsavedChangesGuard";

const STATUS_TONE: Record<string, string> = { DRAFT: "hot", EFFECTIVE: "pass", SUPERSEDED: "muted" };

function DraftEditor({
  spec,
  data,
  onChange,
}: {
  spec: SpecVersion;
  data: SpecificationsResponse;
  onChange: (d: SpecificationsResponse) => void;
}) {
  const { user } = useAuth();
  const toast = useToast();
  const [tests, setTests] = useState<TestDraft[]>(spec.tests);
  const [review, setReview] = useState(spec.review_date ?? "");
  const [methods, setMethods] = useState<MethodChoice[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [signing, setSigning] = useState(false);
  const dirty = JSON.stringify(tests) !== JSON.stringify(spec.tests) || review !== (spec.review_date ?? "");
  const mine = spec.created_by_id === user?.id;

  // Tests are written in the draft itself: the lab does not keep a library of test templates.
  useEffect(() => {
    apiGet<{ methods: MethodChoice[] }>("/api/lab/method-choices/")
      .then((r) => setMethods(r.methods))
      .catch(() => setMethods([]));
  }, []);

  const edit = (i: number, patch: Partial<TestDraft>) =>
    setTests((list) => list.map((t, n) => (n === i ? { ...t, ...patch } : t)));
  const move = (i: number, by: number) =>
    setTests((list) => {
      const next = [...list];
      const [row] = next.splice(i, 1);
      next.splice(i + by, 0, row);
      return next;
    });

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      onChange(await apiPut<SpecificationsResponse>(`/api/specifications/${spec.id}/`, { tests, review_date: review || null }));
      toast("ok", "Draft saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the draft.");
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    setBusy(true);
    try {
      onChange(await apiDelete<SpecificationsResponse>(`/api/specifications/${spec.id}/`));
      toast("ok", "Draft discarded");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not discard the draft.");
      setBusy(false);
    }
  };

  return (
    <div className="spec-draft">
      <div className="spec-draft-head">
        <b>{spec.stage_name ? `${spec.stage_name} tests — draft version ${spec.version}` : `Specification — draft version ${spec.version}`}</b>
        <span className="cell-sub">{spec.created_by ? `By ${spec.created_by}` : ""} · “{spec.change_reason}”</span>
      </div>
      <div className="stack">
        {tests.length === 0 && <div className="cell-sub">No tests yet. Add one below.</div>}
        {tests.map((t, i) => (
          <div className="test-row" key={i}>
            <div className="stage-num">{i + 1}</div>
            <div style={{ minWidth: 0, flex: 1 }}>
              <TestFields test={t} limitTypes={data.limit_types} methods={methods} onChange={(patch) => edit(i, patch)} />
              {t.source && <div className="cell-sub" style={{ marginTop: 6 }}>From template {t.source}</div>}
            </div>
            <div className="stage-tools">
              <button className="icon-btn" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Move test ${i + 1} up`}>↑</button>
              <button className="icon-btn" disabled={i === tests.length - 1} onClick={() => move(i, 1)} aria-label={`Move test ${i + 1} down`}>↓</button>
              <button className="icon-btn danger" onClick={() => setTests((list) => list.filter((_, n) => n !== i))}
                aria-label={`Remove test ${i + 1}`}>✕</button>
            </div>
          </div>
        ))}
        <div className="actions-bar">
          <button className="ghost small" onClick={() => setTests((list) => [...list, { ...BLANK_TEST }])}>+ Add a test</button>
          <div className="spacer" />
          <label className="range-field">Next review
            <input type="date" value={review} onChange={(e) => setReview(e.target.value)} />
          </label>
        </div>
        {error && <Message kind="error">{error}</Message>}
        <div className="actions-bar">
          {data.can_draft && <button className="danger small" disabled={busy} onClick={() => void discard()}>Discard draft</button>}
          <div className="spacer" />
          {data.can_approve && !dirty && (
            mine && !user?.permissions.includes("admin.override") ? (
              <span className="cell-sub">You drafted this, so someone else must make it effective.</span>
            ) : (
              <button className="ghost" disabled={busy} onClick={() => setSigning(true)}>Make effective…</button>
            )
          )}
          {data.can_draft && (
            <button className="primary" disabled={busy || !dirty} onClick={() => void save()}>
              {busy ? "Saving…" : "Save draft"}
            </button>
          )}
        </div>
      </div>
      <UnsavedChangesGuard dirty={dirty} />
      {signing && (
        <SignModal
          title={`Make ${spec.stage_name ? `${spec.stage_name} tests ` : "specification "}version ${spec.version} effective`}
          meaning="Approved by"
          description={spec.stage_name
            ? `Samples registered for ${spec.stage_name} from now on are tested on this version. Samples already registered keep the tests they started with.`
            : "Samples registered from now on use this version. Samples already registered keep the one they started with."}
          onConfirm={async (password) => {
            onChange(await apiPost<SpecificationsResponse>(`/api/specifications/${spec.id}/approve/`, { digest: spec.digest, password }));
            toast("ok", `${spec.stage_name ? `${spec.stage_name} tests, version` : "Specification version"} ${spec.version} is now effective`);
          }}
          onClose={() => setSigning(false)}
        />
      )}
    </div>
  );
}

/**
 * One set of a product's tests, with every version: its own specification (stageKey
 * empty) or one QC stage's own tests. Drafted by one person, made effective by
 * another; shown inside the stage it belongs to.
 */
export default function SpecManager({ productId, stageKey, stageName, onChanged }: {
  productId: number;
  stageKey: string;
  /** The stage these tests are for; absent for the product's own specification. */
  stageName?: string;
  /** Something was drafted, saved or made effective: the stage's summary should be read again. */
  onChanged?: () => void;
}) {
  const toast = useToast();
  const [data, setData] = useState<SpecificationsResponse | null>(null);
  const [error, setError] = useState("");
  const [asking, setAsking] = useState(false);
  const [moving, setMoving] = useState<SpecVersion | null>(null);
  const [newReview, setNewReview] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await apiGet<SpecificationsResponse>(`/api/products/${productId}/specifications/?stage=${encodeURIComponent(stageKey)}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the tests.");
    }
  }, [productId, stageKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const changed = (next: SpecificationsResponse) => {
    setData(next);
    onChanged?.();
  };

  if (error) return <Message kind="error">{error}</Message>;
  if (!data) return <TableSkeleton />;

  const draft = data.specifications.find((s) => s.status === "DRAFT");
  const approved = data.specifications.filter((s) => s.status !== "DRAFT");
  const forStage = Boolean(stageKey);

  return (
    <div className="spec-manager">
      {draft ? (
        <DraftEditor key={JSON.stringify([draft.id, draft.review_date, draft.tests])} spec={draft} data={data} onChange={changed} />
      ) : (
        data.can_draft && (
          <div className="actions-bar">
            <button className="primary small" onClick={() => setAsking(true)}>
              {approved.length ? "Draft a new version" : forStage ? `Draft ${stageName ?? "its"} tests` : "Draft the first specification"}
            </button>
            <span className="cell-sub">A draft changes nothing until someone else makes it effective.</span>
          </div>
        )
      )}

      {approved.length === 0 ? (
        forStage ? (
          <EmptyState title={`No ${stageName ?? "stage"} tests in force yet`}
            sub="Until a version is effective, its samples are tested on the product's specification." />
        ) : (
          <EmptyState title="No approved specification yet" sub="Samples of this product cannot be registered until one is effective." />
        )
      ) : (
        <div className="spec-versions">
          {approved.map((s) => (
            <details className="spec-version" key={s.id} open={s.status === "EFFECTIVE"}>
              <summary>
                <b>Version {s.version}</b>
                <span className={`badge ${STATUS_TONE[s.status]}`}>{s.status_label}</span>
                <span className="cell-sub">
                  {s.effective_date && `Effective ${fmtDate(s.effective_date)}`}
                  {s.approved_by && ` · approved by ${s.approved_by}, ${fmtDateTime(s.approved_at!)}`}
                  {` · ${s.sample_count} sample${s.sample_count === 1 ? "" : "s"}`}
                </span>
              </summary>
              {s.change_reason && <div className="cell-sub" style={{ padding: "0 14px 8px" }}>“{s.change_reason}”</div>}
              <div className="cell-sub" style={{ padding: "0 14px 10px" }}>
                Next review: {s.review_date ? fmtDate(s.review_date) : "not set"}
                {data.can_draft && s.status === "EFFECTIVE" && (
                  <> · <button type="button" className="link-btn" onClick={() => { setNewReview(s.review_date ?? ""); setMoving(s); }}>Change</button></>
                )}
              </div>
              <div className="table-wrap">
                <table className="grid">
                  <thead><tr><th>#</th><th>Test</th><th>Method</th><th>Limit</th><th>Decimals</th><th>Template</th></tr></thead>
                  <tbody>
                    {s.tests.map((t, i) => (
                      <tr key={t.id}>
                        <td>{i + 1}</td>
                        <td className="cell-title">{t.name}</td>
                        <td>{t.method || "—"}</td>
                        <td>{t.limit_text}</td>
                        <td className="num">{t.decimals}</td>
                        <td className="cell-sub">{t.source || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          ))}
        </div>
      )}

      {asking && (
        <CommentModal
          title={forStage ? `Draft ${stageName ?? "stage"} tests` : "Draft a new version of the specification"}
          hint={forStage && approved.length === 0
            ? `It starts empty: add the tests and limits the ${stageName ?? ""} stage is checked against. Nothing changes until someone else makes it effective.`
            : "It starts as a copy of the current version. Nothing changes until someone else makes it effective."}
          label="Why is a new version needed?"
          confirmText="Create draft"
          tone="primary"
          onConfirm={async (reason) => {
            changed(await apiPost<SpecificationsResponse>(`/api/products/${productId}/specifications/`, {
              reason, stage: stageKey,
            }));
            setAsking(false);
            toast("ok", "Draft created");
          }}
          onClose={() => setAsking(false)}
        />
      )}
      {moving && (
        <CommentModal
          title={`Next review of version ${moving.version}`}
          hint="The review date is the one thing that can change on an approved version."
          label="Why is it changing?"
          confirmText="Save"
          tone="primary"
          onConfirm={async (reason) => {
            changed(await apiPatch<SpecificationsResponse>(`/api/specifications/${moving.id}/review-date/`, {
              review_date: newReview, reason,
            }));
            setMoving(null);
          }}
          onClose={() => setMoving(null)}
        >
          <label className="field">New review date
            <input type="date" required value={newReview} onChange={(e) => setNewReview(e.target.value)} />
          </label>
        </CommentModal>
      )}
    </div>
  );
}
