import { useCallback, useEffect, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "../../api";
import ChecklistEditor, { checklistPayload, toChecklistDraft } from "../../components/ChecklistEditor";
import type { ChecklistDraft } from "../../components/ChecklistEditor";
import ConfirmModal from "../../components/ConfirmModal";
import { Message, TableSkeleton } from "../../components/Feedback";
import Stepper from "../../components/Stepper";
import { useToast } from "../../components/Toast";
import UnsavedChangesGuard from "../../components/UnsavedChangesGuard";
import type {
  StepConfig,
  WorkflowAdmin,
  WorkflowAdminStage,
  WorkflowRole,
  WorkflowStage,
  WorkflowsResponse,
  WorkflowVersionRow,
} from "../../types";
import { fmtDateTime } from "../../util";
import ModalBackdrop from "../../components/ModalBackdrop";

/** One row of the stage editor, before it is saved. */
interface StageDraft {
  key: number;
  name: string;
  signature_title: string;
  holder_title: string;
  role_id: number | "";
  requires_acceptance: boolean;
  checklist: ChecklistDraft[];
}

/** The analyst's step: fixed in place, but its requirements are configurable. */
interface TestingDraft {
  requires_acceptance: boolean;
  checklist: ChecklistDraft[];
}

let nextKey = 1;

function toDraft(stages: WorkflowAdminStage[]): StageDraft[] {
  return stages.map((s) => ({
    key: nextKey++,
    name: s.name,
    signature_title: s.signature_title,
    holder_title: s.holder_title,
    role_id: s.role_id,
    requires_acceptance: s.requires_acceptance ?? false,
    checklist: toChecklistDraft(s.checklist ?? []),
  }));
}

function toTestingDraft(testing: StepConfig | undefined): TestingDraft {
  return {
    requires_acceptance: testing?.requires_acceptance ?? false,
    checklist: toChecklistDraft(testing?.checklist ?? []),
  };
}

function toPayload(draft: StageDraft[]) {
  return draft.map(({ name, signature_title, holder_title, role_id, requires_acceptance, checklist }) => ({
    name: name.trim(),
    signature_title: signature_title.trim(),
    holder_title: holder_title.trim(),
    role_id,
    requires_acceptance,
    checklist: checklistPayload(checklist),
  }));
}

function testingPayload(t: TestingDraft) {
  return { requires_acceptance: t.requires_acceptance, checklist: checklistPayload(t.checklist) };
}

/** Compared as the server would receive them, so a no-op edit is not a change. */
function sameStages(
  draft: StageDraft[],
  testing: TestingDraft,
  receipt: ChecklistDraft[],
  showRetests: boolean,
  wf: WorkflowAdmin,
) {
  return (
    JSON.stringify([toPayload(draft), testingPayload(testing), checklistPayload(receipt), showRetests]) ===
    JSON.stringify([
      toPayload(toDraft(wf.stages)),
      testingPayload(toTestingDraft(wf.testing)),
      checklistPayload(toChecklistDraft(wf.receipt.checklist)),
      wf.certificate.show_retests,
    ])
  );
}

function requirementsText(checklist: { length: number }, acceptance?: boolean) {
  const parts = [];
  if (checklist.length) parts.push(`${checklist.length} check${checklist.length === 1 ? "" : "s"}`);
  if (acceptance) parts.push("must be accepted");
  return parts.join(" · ");
}

/** What the stepper shows for a draft — only the fields it reads. */
function previewStages(draft: StageDraft[], roles: WorkflowRole[]): WorkflowStage[] {
  return draft.map((d, i) => {
    const role = roles.find((r) => r.id === d.role_id);
    return {
      order: i + 1,
      code: String(d.key),
      name: d.name || `Stage ${i + 1}`,
      signature_title: d.signature_title,
      holder_title: d.holder_title,
      holder: d.holder_title || role?.name || "—",
      role_id: role?.id ?? 0,
      role_name: role?.name ?? "",
    };
  });
}

function chainText(stages: WorkflowStage[]) {
  return stages.map((s) => s.name).join(" → ");
}

function NewWorkflowModal({
  from,
  onDone,
  onClose,
}: {
  from: WorkflowAdmin | undefined;
  onDone: (created: WorkflowAdmin) => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const created = await apiPost<WorkflowAdmin>("/api/workflows/", {
        name,
        description,
        stages: toPayload(toDraft(from?.stages ?? [])),
        testing: testingPayload(toTestingDraft(from?.testing)),
        receipt: { checklist: checklistPayload(toChecklistDraft(from?.receipt.checklist ?? [])) },
        certificate: { show_retests: from?.certificate.show_retests ?? false },
        reason: from ? `Started as a copy of ${from.name}` : "",
      });
      toast("ok", `Workflow “${name}” created`, "Now set its stages and choose the products that use it.");
      onDone(created);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the workflow.");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3>New review workflow</h3>
        <p className="modal-sub">
          It starts with the same stages as {from ? `“${from.name}”` : "the default"} (
          {from ? chainText(from.stages) : "—"}). Change them on the next screen.
        </p>
        <label className="field">
          Name
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Sterile injectables"
          />
        </label>
        <label className="field">
          Description <span className="note">Optional — when to use it.</span>
          <input value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="primary" onClick={() => void save()} disabled={busy || !name.trim()}>
            {busy ? "Creating…" : "Create workflow"}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}

function HistoryModal({ workflow, onClose }: { workflow: WorkflowAdmin; onClose: () => void }) {
  const [rows, setRows] = useState<WorkflowVersionRow[] | null>(null);

  useEffect(() => {
    apiGet<WorkflowVersionRow[]>(`/api/workflows/${workflow.id}/history/`)
      .then(setRows)
      .catch(() => setRows([]));
  }, [workflow.id]);

  return (
    <ModalBackdrop onClick={onClose}>
      <div
        className="modal wide"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <h3>Version history — {workflow.name}</h3>
        <p className="modal-sub">
          Every set of stages this workflow has had. Each sample keeps the version it was
          registered under, so what any certificate had to carry is always answerable.
        </p>
        {rows === null ? (
          <TableSkeleton rows={3} cols={4} />
        ) : (
          <div className="table-wrap" style={{ maxHeight: 400, overflowY: "auto" }}>
            <table className="grid">
              <thead>
                <tr><th>Version</th><th>Stages</th><th>Saved</th><th>Reason</th><th>Samples</th></tr>
              </thead>
              <tbody>
                {rows.map((v) => (
                  <tr key={v.version}>
                    <td className="num">v{v.version}</td>
                    <td>
                      {requirementsText(v.receipt?.checklist ?? []) && (
                        <div className="cell-sub">Receipt · {requirementsText(v.receipt.checklist)}</div>
                      )}
                      {requirementsText(v.testing?.checklist ?? [], v.testing?.requires_acceptance) && (
                        <div className="cell-sub">Testing · {requirementsText(v.testing.checklist, v.testing.requires_acceptance)}</div>
                      )}
                      {v.stages.map((s) => (
                        <div key={s.order}>
                          {s.order}. {s.name} <span className="cell-sub">· {s.role_name}</span>
                          {requirementsText(s.checklist ?? [], s.requires_acceptance) && (
                            <span className="cell-sub"> · {requirementsText(s.checklist ?? [], s.requires_acceptance)}</span>
                          )}
                        </div>
                      ))}
                      {v.certificate?.show_retests && <div className="cell-sub">Certificate shows retests</div>}
                    </td>
                    <td>
                      {fmtDateTime(v.created_at)}
                      <div className="cell-sub">{v.created_by_name}</div>
                    </td>
                    <td>{v.reason || "—"}</td>
                    <td className="num">{v.sample_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="actions">
          <button className="ghost" onClick={onClose}>Close</button>
        </div>
      </div>
    </ModalBackdrop>
  );
}

export default function Workflows() {
  const toast = useToast();
  const [data, setData] = useState<WorkflowsResponse | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draft, setDraft] = useState<StageDraft[]>([]);
  const [testing, setTesting] = useState<TestingDraft>(toTestingDraft(undefined));
  const [receipt, setReceipt] = useState<ChecklistDraft[]>([]);
  const [showRetests, setShowRetests] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [leaving, setLeaving] = useState<(() => void) | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await apiGet<WorkflowsResponse>("/api/workflows/");
      setData(d);
      setSelectedId((prev) => prev ?? d.workflows[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load workflows.");
      setData({ workflows: [], products: [], roles: [], max_stages: 10, file_types: [], max_upload_mb: 20 });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = data?.workflows.find((w) => w.id === selectedId) ?? null;

  const resetRequirements = (wf: WorkflowAdmin) => {
    setDraft(toDraft(wf.stages));
    setTesting(toTestingDraft(wf.testing));
    setReceipt(toChecklistDraft(wf.receipt.checklist));
    setShowRetests(wf.certificate.show_retests);
  };

  // Reset the editor whenever a different workflow (or a new version) is opened.
  useEffect(() => {
    if (selected) {
      resetRequirements(selected);
      setName(selected.name);
      setDescription(selected.description);
      setReason("");
      setError("");
    }
  }, [selected?.id, selected?.version]); // eslint-disable-line react-hooks/exhaustive-deps

  if (data === null) {
    return <div className="card"><div className="card-body flush"><TableSkeleton /></div></div>;
  }

  const roles = data.roles;
  const defaultWorkflow = data.workflows.find((w) => w.is_default);
  const stagesDirty = selected !== null && !sameStages(draft, testing, receipt, showRetests, selected);
  const detailsDirty =
    selected !== null && (name.trim() !== selected.name || description.trim() !== selected.description);
  // Choosing another workflow replaces the editor without changing the address, so the guard cannot see it.
  const unlessUnsaved = (action: () => void) => (stagesDirty || detailsDirty ? setLeaving(() => action) : action());
  const incomplete = draft.findIndex((d) => !d.name.trim() || !d.signature_title.trim() || d.role_id === "");
  const unlabelled = [receipt, testing.checklist, ...draft.map((d) => d.checklist)].some((c) => c.some((i) => !i.label.trim()));
  const productsUsing = (wf: WorkflowAdmin) =>
    data.products.filter((p) => p.workflow_id === wf.id || (wf.is_default && p.workflow_id === null)).length;

  const edit = (key: number, patch: Partial<StageDraft>) =>
    setDraft((prev) => prev.map((d) => (d.key === key ? { ...d, ...patch } : d)));
  const move = (index: number, by: number) =>
    setDraft((prev) => {
      const next = [...prev];
      const [row] = next.splice(index, 1);
      next.splice(index + by, 0, row);
      return next;
    });
  const remove = (key: number) => setDraft((prev) => prev.filter((d) => d.key !== key));
  const add = () =>
    setDraft((prev) => [
      ...prev,
      { key: nextKey++, name: "", signature_title: "", holder_title: "", role_id: "", requires_acceptance: false, checklist: [] },
    ]);

  const run = async (action: () => Promise<unknown>, ok: string, sub?: string) => {
    setBusy(true);
    setError("");
    try {
      await action();
      toast("ok", ok, sub);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  };

  const saveStages = () =>
    selected &&
    run(
      () => apiPut(`/api/workflows/${selected.id}/stages/`, {
        stages: toPayload(draft),
        testing: testingPayload(testing),
        receipt: { checklist: checklistPayload(receipt) },
        certificate: { show_retests: showRetests },
        reason,
      }),
      `${selected.name} saved as version ${(selected.version ?? 0) + 1}`,
      "Samples already registered keep the version they started with.",
    );

  const saveDetails = () =>
    selected &&
    run(() => apiPatch(`/api/workflows/${selected.id}/`, { name, description }), "Workflow renamed");

  const makeDefault = () =>
    selected &&
    run(
      () => apiPatch(`/api/workflows/${selected.id}/`, { is_default: true }),
      `${selected.name} is now the default`,
      "Products without a workflow of their own use it for new samples.",
    );

  const deleteWorkflow = () =>
    selected &&
    run(async () => {
      await apiDelete(`/api/workflows/${selected.id}/`);
      setSelectedId(null);
    }, `${selected.name} deleted`);

  const assign = async (productId: number, workflowId: number | null) => {
    try {
      await apiPut(`/api/products/${productId}/workflow/`, { workflow_id: workflowId });
      const product = data.products.find((p) => p.id === productId);
      const wf = data.workflows.find((w) => w.id === workflowId);
      toast("ok", `${product?.name ?? "Product"} updated`,
        `New samples will go through ${wf ? wf.name : "the default workflow"}.`);
      await load();
    } catch (err) {
      toast("error", "Could not change the workflow", err instanceof Error ? err.message : undefined);
    }
  };

  return (
    <>
      <div className="page-head">
        <h1>Review workflows</h1>
        <p className="sub">
          After the analyst signs, a certificate goes through the review stages of its product’s
          workflow, in order — the last signature releases it. Some products need one review, some
          need several. Changing a workflow saves a new version: samples already registered keep
          the stages they started with.
        </p>
      </div>

      <div className="split">
        <div className="card" style={{ margin: 0 }}>
          <div className="card-head">
            <h2>Workflows</h2>
            <div className="spacer" />
            <button className="ghost small" onClick={() => unlessUnsaved(() => setShowNew(true))}>+ New</button>
          </div>
          <div className="card-body flush">
            {data.workflows.map((w) => (
              <button
                key={w.id}
                onClick={() => w.id !== selectedId && unlessUnsaved(() => setSelectedId(w.id))}
                style={{
                  display: "block", width: "100%", textAlign: "left", font: "inherit",
                  padding: "12px 16px", border: "none", cursor: "pointer",
                  borderBottom: "1px solid var(--line)",
                  background: w.id === selectedId ? "var(--brand-soft)" : "transparent",
                  color: w.id === selectedId ? "var(--brand-soft-ink)" : "var(--ink)",
                }}
              >
                <div style={{ fontWeight: 650, display: "flex", alignItems: "center", gap: 7 }}>
                  {w.name}
                  {w.is_default && <span className="badge info">Default</span>}
                </div>
                <div className="chain-pills" aria-label={`Analysed, then ${chainText(w.stages)}`}>
                  <span>Analysed</span>
                  {w.stages.map((s) => <span key={s.order}>{s.name}</span>)}
                </div>
                <div className="cell-sub">
                  {w.stages.length + 1} signatures · v{w.version} · {productsUsing(w)} product{productsUsing(w) === 1 ? "" : "s"}
                  {w.in_review_count > 0 && ` · ${w.in_review_count} in review`}
                </div>
              </button>
            ))}
          </div>
        </div>

        {selected && (
          <div className="card" style={{ margin: 0 }}>
            <div className="card-head">
              <h2>{selected.name}</h2>
              <span className="hint">version {selected.version}</span>
              {selected.is_default && <span className="badge info">Default</span>}
              <div className="spacer" />
              <button className="ghost small" onClick={() => setShowHistory(true)}>History</button>
              {!selected.is_default && (
                <button className="ghost small" disabled={busy} onClick={() => void makeDefault()}>
                  Make default
                </button>
              )}
              {!selected.is_default && selected.sample_count === 0 && productsUsing(selected) === 0 && (
                <button className="danger small" disabled={busy} onClick={() => void deleteWorkflow()}>
                  Delete
                </button>
              )}
            </div>
            <div className="card-body">
              <div className="form-row" style={{ marginBottom: 6 }}>
                <label className="field">
                  Name
                  <input value={name} onChange={(e) => setName(e.target.value)} />
                </label>
                <label className="field">
                  Description
                  <input value={description} onChange={(e) => setDescription(e.target.value)} />
                </label>
              </div>
              {detailsDirty && (
                <div className="actions-bar" style={{ marginBottom: 14 }}>
                  <div className="spacer" />
                  <button className="ghost small" onClick={() => { setName(selected.name); setDescription(selected.description); }}>
                    Discard
                  </button>
                  <button className="primary small" disabled={busy || !name.trim()} onClick={() => void saveDetails()}>
                    Save name
                  </button>
                </div>
              )}

              <div style={{ margin: "14px 0 18px" }}>
                <Stepper status={null} stages={previewStages(draft, roles)} />
              </div>

              <div className="stage-list">
                <div className="stage-card fixed">
                  <div className="stage-num" aria-hidden="true">☑</div>
                  <div style={{ minWidth: 0 }}>
                    <div className="stage-title">Received — receipt checks</div>
                    <div className="cell-sub">
                      What the front desk checks when a sample arrives, such as the seal, the label and
                      the temperature. With checks here, testing cannot start until they are complete.
                      Leave it empty and samples go straight to the analyst.
                    </div>
                    <details className="cl-details" open={receipt.length > 0}>
                      <summary>Checklist and required documents ({receipt.length})</summary>
                      <ChecklistEditor
                        items={receipt}
                        onChange={setReceipt}
                        fileTypes={data.file_types}
                        maxMb={data.max_upload_mb}
                      />
                    </details>
                  </div>
                  <span className="badge muted">Fixed</span>
                </div>

                <div className="stage-card fixed">
                  <div className="stage-num" aria-hidden="true">✎</div>
                  <div style={{ minWidth: 0 }}>
                    <div className="stage-title">Tested — “Analysed by”</div>
                    <div className="cell-sub">
                      Signed by the analyst assigned to the sample. Always the first signature; it
                      freezes the certificate.
                    </div>
                    <label className="cl-flag" style={{ marginTop: 10 }}>
                      <input
                        type="checkbox"
                        checked={testing.requires_acceptance}
                        onChange={(e) => setTesting((t) => ({ ...t, requires_acceptance: e.target.checked }))}
                      />
                      The analyst must accept the sample (confirm receipt) before entering results
                    </label>
                    <details className="cl-details" open={testing.checklist.length > 0}>
                      <summary>Checklist and required documents ({testing.checklist.length})</summary>
                      <ChecklistEditor
                        items={testing.checklist}
                        onChange={(checklist) => setTesting((t) => ({ ...t, checklist }))}
                        fileTypes={data.file_types}
                        maxMb={data.max_upload_mb}
                      />
                    </details>
                  </div>
                  <span className="badge muted">Fixed</span>
                </div>

                {draft.map((d, i) => {
                  const role = roles.find((r) => r.id === d.role_id);
                  const prints = d.signature_title.trim()
                    ? `${d.signature_title.trim()}${d.holder_title.trim() ? ` (${d.holder_title.trim()})` : ""}`
                    : "";
                  return (
                    <div key={d.key} className="stage-card">
                      <div className="stage-num">{i + 1}</div>
                      <div className="stage-fields">
                        <label className="field">
                          Stage name
                          <input
                            value={d.name}
                            onChange={(e) => edit(d.key, { name: e.target.value })}
                            placeholder="e.g. Checked"
                            maxLength={60}
                          />
                        </label>
                        <label className="field">
                          Signature title
                          <input
                            value={d.signature_title}
                            onChange={(e) => edit(d.key, { signature_title: e.target.value })}
                            placeholder="e.g. Checked by"
                            maxLength={60}
                          />
                        </label>
                        <label className="field">
                          Holder (optional)
                          <input
                            value={d.holder_title}
                            onChange={(e) => edit(d.key, { holder_title: e.target.value })}
                            placeholder="e.g. AM / DM"
                            maxLength={60}
                          />
                        </label>
                        <label className="field wide">
                          Signed by role
                          <select
                            value={d.role_id}
                            onChange={(e) => edit(d.key, { role_id: e.target.value ? Number(e.target.value) : "" })}
                          >
                            <option value="">— choose the role that signs —</option>
                            {roles.map((r) => (
                              <option key={r.id} value={r.id}>{r.name}</option>
                            ))}
                          </select>
                        </label>
                        <div className="wide-all">
                          <label className="cl-flag">
                            <input
                              type="checkbox"
                              checked={d.requires_acceptance}
                              onChange={(e) => edit(d.key, { requires_acceptance: e.target.checked })}
                            />
                            Must be taken, or accepted when assigned, before anyone signs it
                          </label>
                          <details className="cl-details" open={d.checklist.length > 0}>
                            <summary>Checklist and required documents ({d.checklist.length})</summary>
                            <ChecklistEditor
                              items={d.checklist}
                              onChange={(checklist) => edit(d.key, { checklist })}
                              fileTypes={data.file_types}
                              maxMb={data.max_upload_mb}
                            />
                          </details>
                        </div>
                        <div className="stage-meta">
                          {role && (
                            <span className={role.user_count === 0 ? "stage-warn" : ""}>
                              {role.user_count === 0
                                ? "Nobody holds this role yet"
                                : `${role.user_count} person${role.user_count === 1 ? "" : "s"} can sign`}
                            </span>
                          )}
                          {prints && <span>Prints as “{prints}”</span>}
                          {i === draft.length - 1 && <span className="badge pass">Releases the certificate</span>}
                        </div>
                      </div>
                      <div className="stage-tools">
                        <button className="icon-btn" disabled={i === 0} onClick={() => move(i, -1)}
                          aria-label={`Move stage ${i + 1} up`} title="Move up">↑</button>
                        <button className="icon-btn" disabled={i === draft.length - 1} onClick={() => move(i, 1)}
                          aria-label={`Move stage ${i + 1} down`} title="Move down">↓</button>
                        <button className="icon-btn danger" disabled={draft.length === 1} onClick={() => remove(d.key)}
                          aria-label={`Remove stage ${i + 1}`} title="Remove stage">✕</button>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="actions-bar" style={{ margin: "12px 0 16px" }}>
                <button className="ghost small" disabled={draft.length >= data.max_stages} onClick={add}>
                  + Add stage
                </button>
                <span style={{ fontSize: 12.5, color: "var(--ink-3)" }}>
                  The last stage releases the certificate. Every signature must come from a different
                  person — a role on two stages needs two people.
                </span>
              </div>

              <div className="stage-list" style={{ marginBottom: 16 }}>
                <div className="stage-card fixed">
                  <div className="stage-num" aria-hidden="true">▤</div>
                  <div style={{ minWidth: 0 }}>
                    <div className="stage-title">Printed certificate</div>
                    <div className="cell-sub">
                      Off: the certificate reports the final result only. On: it also lists each retest:
                      the failed result, the reason, who authorized it and the retest result. The full
                      history always stays on the sample page, and every copy of a certificate prints
                      the same.
                    </div>
                    <label className="cl-flag" style={{ marginTop: 10 }}>
                      <input
                        type="checkbox"
                        checked={showRetests}
                        onChange={(e) => setShowRetests(e.target.checked)}
                      />
                      Show retests on the printed certificate
                    </label>
                  </div>
                </div>
              </div>

              {!stagesDirty && selected.warnings.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <Message kind="warn">
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {selected.warnings.map((w) => <li key={w}>{w}</li>)}
                    </ul>
                  </Message>
                </div>
              )}

              {error && <div style={{ marginBottom: 12 }}><Message kind="error">{error}</Message></div>}

              {stagesDirty && (
                <div style={{ display: "grid", gap: 12 }}>
                  {incomplete >= 0 && (
                    <Message kind="info">
                      Stage {incomplete + 1} needs a name, a signature title and a role before it can be saved.
                    </Message>
                  )}
                  {unlabelled && (
                    <Message kind="info">Every checklist item needs a label before it can be saved.</Message>
                  )}
                  <label className="field">
                    Reason for this change <span className="note">Kept with the version history.</span>
                    <input
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      placeholder="e.g. QA review added under change request CR-2026-031"
                    />
                  </label>
                  <div className="actions-bar">
                    <button className="ghost" onClick={() => resetRequirements(selected)} disabled={busy}>
                      Discard changes
                    </button>
                    <div className="spacer" />
                    <span style={{ fontSize: 13, color: "var(--ink-3)" }}>
                      {selected.in_review_count > 0
                        ? `${selected.in_review_count} sample${selected.in_review_count === 1 ? "" : "s"} in review keep version ${selected.version}.`
                        : "Applies to samples registered from now on."}
                    </span>
                    <button className="primary" onClick={() => void saveStages()} disabled={busy || incomplete >= 0 || unlabelled}>
                      {busy ? "Saving…" : `Save as version ${(selected.version ?? 0) + 1}`}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head">
          <h2>Products</h2>
          <span className="hint">Which workflow each product’s new samples go through</span>
        </div>
        <div className="card-body flush">
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr><th>Product</th><th>Section</th><th>Review workflow</th><th>Signatures</th></tr>
              </thead>
              <tbody>
                {data.products.map((p) => {
                  const wf = data.workflows.find((w) => w.id === p.workflow_id) ?? defaultWorkflow;
                  return (
                    <tr key={p.id}>
                      <td>
                        <div className="cell-title">{p.name}</div>
                        <div className="cell-sub">{p.code}</div>
                      </td>
                      <td>{p.section}</td>
                      <td>
                        <select
                          value={p.workflow_id ?? ""}
                          onChange={(e) => void assign(p.id, e.target.value ? Number(e.target.value) : null)}
                          aria-label={`Workflow for ${p.name}`}
                          style={{ maxWidth: 280 }}
                        >
                          <option value="">Default ({defaultWorkflow?.name ?? "none"})</option>
                          {data.workflows.map((w) => (
                            <option key={w.id} value={w.id}>{w.name}</option>
                          ))}
                        </select>
                      </td>
                      <td>
                        {wf ? (
                          <>
                            {wf.stages.length + 1}
                            <div className="cell-sub">Analysed → {chainText(wf.stages)}</div>
                          </>
                        ) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {showNew && (
        <NewWorkflowModal
          from={selected ?? defaultWorkflow}
          onDone={(created) => {
            setSelectedId(created.id);
            void load();
          }}
          onClose={() => setShowNew(false)}
        />
      )}
      {showHistory && selected && (
        <HistoryModal workflow={selected} onClose={() => setShowHistory(false)} />
      )}
      {leaving && (
        <ConfirmModal
          title="Discard your changes?"
          confirmText="Discard changes"
          cancelText="Keep editing"
          onConfirm={() => {
            leaving();
            setLeaving(null);
          }}
          onClose={() => setLeaving(null)}
        >
          The changes to this workflow have not been saved.
        </ConfirmModal>
      )}
      <UnsavedChangesGuard dirty={stagesDirty || detailsDirty} />
    </>
  );
}
