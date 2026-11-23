import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { apiGet, apiPut } from "../api";
import { modeShown } from "../stageKinds";
import type { StageMode } from "../stageKinds";
import type { ProductStagesResponse, StageKind } from "../types";
import CopyStagesModal from "./CopyStagesModal";
import type { CopiedStages } from "./CopyStagesModal";
import { Message } from "./Feedback";
import RowTools from "./RowTools";
import StagesView from "./StagesView";
import StageVersions from "./StageVersions";
import StageTemplateEditor, { blankStep, toDraft, toPayload } from "./StageTemplateEditor";
import type { DraftSignoff, DraftStep } from "./StageTemplateEditor";
import { useToast } from "./Toast";

interface Draft {
  key: number;
  /** Which tests its samples get, kept when it is renamed. Empty for a new stage. */
  testsKey: string;
  name: string;
  description: string;
  mode: Mode;
  required: boolean;
  after_previous: boolean;
  /** A recorded stage's batch record: its steps and sign-off columns. */
  steps: DraftStep[];
  signoffs: DraftSignoff[];
  /** Signed under every step, as on the paper record, or once for the stage. */
  sign_each_step: boolean;
  /** Unfolded in the editor; not saved. */
  open: boolean;
}

let nextKey = 1;

/**
 * How a stage is done, as the editor offers it. A batch record and a QA record are
 * both recorded stages on the server; a batch record is the one with steps and
 * sign-off columns.
 */
type Mode = StageMode;
const MODES: { value: Mode; label: string; note: string }[] = [
  { value: "RECORD", label: "Batch record",
    note: "Production fills its steps and signs its columns in order; it passes when the last column is signed." },
  { value: "TESTED", label: "Tested in the lab",
    note: "The front desk registers samples for it; it passes when they are approved with a certificate." },
  { value: "QA", label: "QA pass / fail",
    note: "QA records it passed or failed on each batch, with remarks and a password, as for a line clearance." },
];

/**
 * The ways a stage may be done here: those the lab offers (stageKinds.ts), and always the
 * stage's own, so a stage saved under a kind no longer offered keeps it when saved again.
 */
const modesFor = (mode: Mode) => MODES.filter((m) => modeShown(m.value) || m.value === mode);

/** What "Add stage" adds, from the kinds offered. */
const ADD_HINT = MODES.every((m) => modeShown(m.value))
  ? "A batch record page, a lab test, or a QA pass / fail check, after the stages above"
  : MODES.filter((m) => modeShown(m.value)).length === 1
    ? "A batch record page: its steps, check points and sign-off columns, after the stages above"
    : `${MODES.filter((m) => modeShown(m.value)).map((m) => m.label).join(" or ")}, after the stages above`;

/** One line for a folded stage: how it is done and what it holds. */
function summary(s: Draft): string {
  const parts = [MODES.find((m) => m.value === s.mode)?.label ?? ""];
  if (s.mode === "RECORD") {
    const points = s.steps.reduce((n, st) => n + st.checkpoints.length, 0);
    parts.push(`${s.steps.length} step${s.steps.length === 1 ? "" : "s"}`, `${points} check point${points === 1 ? "" : "s"}`,
      `${s.signoffs.length} sign-off${s.signoffs.length === 1 ? "" : "s"} ${s.sign_each_step ? "at every step" : "once"}`);
  }
  parts.push(s.required ? "Required" : "Optional");
  if (s.after_previous) parts.push("Waits for earlier stages");
  return parts.join(" · ");
}

const CHEVRON = "M9 6l6 6-6 6";

function modeOf(kind: StageKind, signoffs: number): Mode {
  return kind === "TESTED" ? "TESTED" : signoffs ? "RECORD" : "QA";
}

/**
 * The QC stages every new batch of this product goes through, in order. Saving is a
 * new version: batches already created keep the stages they started with.
 */
export default function QcStagesEditor({ productId, focus }: {
  productId: number;
  /** Open one set of tests to begin with: a stage's key, or "" for the product's specification. */
  focus?: string | null;
}) {
  const toast = useToast();
  const [data, setData] = useState<ProductStagesResponse | null>(null);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Draft[] | null>(null);
  const [reason, setReason] = useState("");
  const [saveError, setSaveError] = useState("");
  const [busy, setBusy] = useState(false);
  // Choosing stages to copy from a product already set up.
  const [copying, setCopying] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await apiGet<ProductStagesResponse>(`/api/products/${productId}/qc-stages/`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the QC stages.");
    }
  }, [productId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Opened from the QC stages column of the product list: go straight to this card.
  const { hash } = useLocation();
  const card = useRef<HTMLElement>(null);
  useEffect(() => {
    if (data && hash === "#qc-stages") card.current?.scrollIntoView({ block: "start" });
  }, [data, hash]);

  // “Change” on one stage: once the editor is open, bring that stage into view.
  const [focusEdit, setFocusEdit] = useState<number | null>(null);
  useEffect(() => {
    if (focusEdit === null || !draft) return;
    document.getElementById(`stage-edit-${focusEdit}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
    setFocusEdit(null);
  }, [focusEdit, draft]);

  if (error) return <Message kind="error">{error}</Message>;
  if (!data) return null;

  const current = data.current?.stages ?? [];
  const startEditing = (stageId?: number) => {
    // From one stage's Change, only that stage opens; otherwise all open unless there are many.
    setDraft(current.map((s) => ({
      key: nextKey++, testsKey: s.key, name: s.name, description: s.description, mode: modeOf(s.kind, s.signoffs.length),
      required: s.required, after_previous: s.after_previous, ...toDraft(s),
      open: stageId !== undefined ? s.id === stageId : current.length <= 2,
    })));
    setReason("");
    setSaveError("");
    const at = current.findIndex((s) => s.id === stageId);
    setFocusEdit(at >= 0 ? at : null);
  };
  const edit = (key: number, patch: Partial<Draft>) =>
    setDraft((d) => d && d.map((s) => (s.key === key ? { ...s, ...patch } : s)));
  const move = (i: number, by: number) =>
    setDraft((d) => {
      if (!d) return d;
      const next = [...d];
      [next[i], next[i + by]] = [next[i + by], next[i]];
      return next;
    });
  // Another product's stages, added after these as new stages of this product: steps,
  // check points, limits and sign-off columns as they are there, folded for checking.
  const addCopied = ({ product, version, stages }: CopiedStages) => {
    setDraft((d) => [
      ...(d ?? []),
      ...stages.map((s) => ({
        // No key: a new stage here, so its samples get this product's tests, never the source's.
        key: nextKey++, testsKey: "", name: s.name, description: s.description, mode: modeOf(s.kind, s.signoffs.length),
        required: s.required, after_previous: s.after_previous, ...toDraft(s), open: false,
      })),
    ]);
    setReason((r) => r || `Stages copied from ${product.code} ${product.name}, version ${version}.`);
    setCopying(false);
    toast("ok", `${stages.length} stage${stages.length === 1 ? "" : "s"} added from ${product.code}`,
      "Check each one, change what differs for this product, then save.");
  };

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    setSaveError("");
    try {
      const saved = await apiPut<ProductStagesResponse>(`/api/products/${productId}/qc-stages/`, {
        stages: draft.map(({ testsKey, name, description, mode, required, after_previous, steps, signoffs, sign_each_step }, i) => ({
          key: testsKey, name, description, kind: mode === "TESTED" ? "TESTED" : "RECORDED", required,
          after_previous: i > 0 && after_previous,
          ...(mode === "RECORD" ? toPayload(steps, signoffs, sign_each_step) : { steps: [], signoffs: [], sign_each_step: false }),
        })),
        reason,
      });
      const changed = saved.current?.version !== data.current?.version;
      setData(saved);
      setDraft(null);
      toast("ok", changed ? `Saved as version ${saved.current?.version}` : "Nothing changed",
        changed ? "New batches go through these stages. Batches already created keep theirs." : undefined);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not save the stages.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={`card${draft ? " qcs-editing" : ""}`} aria-label="QC stages" id="qc-stages" ref={card}
      style={{ scrollMarginTop: 96 }}>
      <div className="card-head">
        <h2>QC stages</h2>
        <span className="hint">
          {data.current
            ? `Version ${data.current.version} · every new batch goes through these, in order`
            : "Every new batch goes through these, in order"}
        </span>
        <div className="spacer" />
        {data.can_manage && !draft && current.length === 0 && (
          <button className="ghost small" onClick={() => { startEditing(); setCopying(true); }}>
            Copy from another product…
          </button>
        )}
        {data.can_manage && !draft && (
          <button className="primary small" onClick={() => startEditing()}>
            {current.length ? "Change stages" : "Set up stages"}
          </button>
        )}
      </div>

      {draft ? (
        <div className="card-body qcs-edit-body">
          <Message kind="info">
            Saving makes a new version for batches created from now on. Batches already created keep the stages
            they started with.
          </Message>
          {draft.length === 0 && (
            <p className="cell-sub" style={{ margin: 0 }}>No stages: new batches will have none to pass.</p>
          )}
          {draft.length > 2 && (
            <div className="actions-bar se-all">
              <button type="button" className="link-btn" onClick={() => setDraft((d) => d && d.map((x) => ({ ...x, open: true })))}>
                Open all
              </button>
              <button type="button" className="link-btn" onClick={() => setDraft((d) => d && d.map((x) => ({ ...x, open: false })))}>
                Fold all
              </button>
            </div>
          )}
          {draft.map((s, i) => (
            <div className={`stage-edit${s.open ? " open" : ""}`} key={s.key} id={`stage-edit-${i}`} style={{ scrollMarginTop: 96 }}>
              <div className="se-head">
                <button type="button" className="se-toggle" aria-expanded={s.open}
                  aria-label={`${s.open ? "Fold" : "Open"} stage ${i + 1}`} onClick={() => edit(s.key, { open: !s.open })}>
                  <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                    <path d={CHEVRON} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
                <span className="se-eyebrow">Stage {i + 1}</span>
                <input className="se-name" value={s.name} maxLength={80} aria-label={`Stage ${i + 1} name`}
                  onChange={(e) => edit(s.key, { name: e.target.value })}
                  placeholder={`Name, e.g. ${s.mode === "RECORD" ? "Bulking (Lot-C)" : s.mode === "TESTED" ? "Final grain" : "Line clearance"}`} />
                <RowTools noun="stage" n={i + 1}
                  onUp={i > 0 ? () => move(i, -1) : undefined}
                  onDown={i < draft.length - 1 ? () => move(i, 1) : undefined}
                  onRemove={() => setDraft((d) => d && d.filter((x) => x.key !== s.key))} />
              </div>
              {!s.open && (
                <button type="button" className="se-summary" onClick={() => edit(s.key, { open: true })}>
                  {summary(s)}
                </button>
              )}
              {s.open && (
                <div className="se-body">
                  <div className="se-settings">
                    {/* Only one way offered (a batch record): nothing to choose. */}
                    {modesFor(s.mode).length > 1 && (
                    <div className="se-mode-field">
                      <span className="se-label">How it is done</span>
                      <div className="seg se-mode" role="group" aria-label={`Stage ${i + 1}: how it is done`}>
                        {modesFor(s.mode).map((m) => (
                          <button key={m.value} type="button" className={s.mode === m.value ? "on" : ""} aria-pressed={s.mode === m.value}
                            onClick={() => edit(s.key, {
                              mode: m.value,
                              // A batch record starts with a step to fill in.
                              ...(m.value === "RECORD" && s.steps.length === 0 ? { steps: [blankStep()] } : {}),
                            })}>
                            {m.label}
                          </button>
                        ))}
                      </div>
                      <span className="cell-sub">{MODES.find((m) => m.value === s.mode)?.note}</span>
                    </div>
                    )}
                    <div className="se-switches">
                      <label className="switch-field">
                        <input type="checkbox" role="switch" className="switch" checked={s.required}
                          aria-label={`Stage ${i + 1} required for release`}
                          onChange={(e) => edit(s.key, { required: e.target.checked })} />
                        <span>Required for release</span>
                      </label>
                      {i > 0 && (
                        <label className="switch-field">
                          <input type="checkbox" role="switch" className="switch" checked={s.after_previous}
                            aria-label={`Stage ${i + 1} waits for the stages before it`}
                            onChange={(e) => edit(s.key, { after_previous: e.target.checked })} />
                          <span>Waits for the stages before it</span>
                        </label>
                      )}
                    </div>
                  </div>
                  <label className="field se-desc">
                    <span>Description <span className="note">(optional)</span></span>
                    <input value={s.description} maxLength={300} onChange={(e) => edit(s.key, { description: e.target.value })}
                      placeholder={s.mode === "TESTED" ? "e.g. LOD and assay of the final grain"
                        : s.mode === "RECORD" ? "e.g. As on page 4 of the batch record" : "e.g. Area, equipment and documents cleared"} />
                  </label>
                  {s.mode === "RECORD" && (
                    <StageTemplateEditor stageNo={i + 1} steps={s.steps} signoffs={s.signoffs} signEachStep={s.sign_each_step}
                      presets={data.checkpoint_presets} roles={data.roles}
                      onSteps={(steps) => edit(s.key, { steps })} onSignoffs={(signoffs) => edit(s.key, { signoffs })}
                      onSignEachStep={(sign_each_step) => edit(s.key, { sign_each_step })}
                      onPresetAdded={(kind) => setData((d) => d && { ...d, checkpoint_presets: [...d.checkpoint_presets, kind] })} />
                  )}
                </div>
              )}
            </div>
          ))}
          <button type="button" className="se-add-stage" onClick={() => {
            setDraft((d) => [
              ...(d ?? []), {
                // A new stage is a batch record, its first step ready to fill in; "How it is done" changes it.
                key: nextKey++, testsKey: "", name: "", description: "", mode: "RECORD", required: true, after_previous: false,
                // Signed under every step, as the paper record is; "Once for the stage" changes it.
                steps: [blankStep()], signoffs: [], sign_each_step: true, open: true,
              },
            ]);
            // Bring the new stage into view, ready for its name.
            setFocusEdit(draft.length);
          }}>
            <span className="se-add-plus" aria-hidden="true">+</span>
            <span>
              <b>Add stage {draft.length + 1}</b>
              <span className="cell-sub">{ADD_HINT}</span>
            </span>
          </button>
          <button type="button" className="se-add-stage" onClick={() => setCopying(true)}>
            <span className="se-add-plus" aria-hidden="true">⧉</span>
            <span>
              <b>Copy stages from another product</b>
              <span className="cell-sub">All of a product's stages, or the ones you tick, with every step, limit and sign-off column</span>
            </span>
          </button>
          {copying && (
            <CopyStagesModal productId={productId} taken={new Set(draft.map((s) => s.name.trim().toLowerCase()))}
              onCopy={addCopied} onClose={() => setCopying(false)} />
          )}
          <div className="se-footer">
            <div className="se-footer-row">
              <label className="field se-reason">
                <span>
                  Why are the stages changing?{" "}
                  <span className="note">
                    {draft.length} stage{draft.length === 1 ? "" : "s"}, {draft.filter((s) => s.required).length} required for release
                  </span>
                </span>
                <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)}
                  placeholder="e.g. Stages taken from batch record BMR-FLX-03, change control CC-2026-0004" />
              </label>
              <div className="actions-bar se-footer-actions">
                <button className="ghost" onClick={() => setDraft(null)} disabled={busy}>Cancel</button>
                <button className="primary" onClick={() => void save()} disabled={busy}>
                  {busy ? "Saving…" : `Save as version ${(data.current?.version ?? 0) + 1}`}
                </button>
              </div>
            </div>
            {saveError && <Message kind="error">{saveError}</Message>}
          </div>
        </div>
      ) : (
        <StagesView data={data} productId={productId} focus={focus} onChanged={() => void load()}
          onEdit={data.can_manage ? (id) => startEditing(id) : undefined} />
      )}

      {!draft && data.versions.length > 0 && <StageVersions data={data} productId={productId} />}
    </section>
  );
}
