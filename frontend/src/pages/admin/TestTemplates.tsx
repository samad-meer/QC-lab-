import { useState } from "react";
import { apiPost } from "../../api";
import { Message } from "../../components/Feedback";
import Field from "../../components/Field";
import ListCard from "../../components/list/ListCard";
import TextFilter from "../../components/list/TextFilter";
import { BLANK_TEST, TestFields } from "../../components/TestRowsEditor";
import { useToast } from "../../components/Toast";
import type { LimitKind, TestDraft, TestTemplateRow } from "../../types";
import { useList, useUrlFilters } from "../../useList";
import { fmtDateTime } from "../../util";
import ModalBackdrop from "../../components/ModalBackdrop";

interface Extras {
  limit_types: LimitKind[];
  can_manage: boolean;
}

function TemplateModal({
  editing,
  limitTypes,
  onDone,
  onClose,
}: {
  editing: TestTemplateRow | null;
  limitTypes: LimitKind[];
  onDone: () => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const [code, setCode] = useState(editing?.code ?? "");
  const [test, setTest] = useState<TestDraft>(editing ?? BLANK_TEST);
  const [retired, setRetired] = useState(editing?.is_retired ?? false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await (editing
        ? apiPost(`/api/test-templates/${encodeURIComponent(editing.code)}/versions/`, { ...test, is_retired: retired, reason })
        : apiPost("/api/test-templates/", { ...test, code }));
      toast("ok", editing ? `Version ${editing.version + 1} saved` : "Template added",
        editing ? "Specifications already using it keep their copy." : undefined);
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the template.");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal wide" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3>{editing ? `New version of ${editing.code}` : "New test template"}</h3>
        <p className="modal-sub">
          A template is copied into a specification. Changing it later never touches a specification that used it.
        </p>
        {!editing && (
          <Field label="Template code" required hint="Short and stable, e.g. ASSAY-HPLC">
            <input value={code} onChange={(e) => setCode(e.target.value)} autoFocus />
          </Field>
        )}
        <TestFields test={test} limitTypes={limitTypes} onChange={(patch) => setTest((t) => ({ ...t, ...patch }))} />
        {editing && (
          <>
            <label className="cl-flag">
              <input type="checkbox" checked={retired} onChange={(e) => setRetired(e.target.checked)} />
              Retired — no longer offered in new specifications
            </label>
            <Field label="Why is it changing?" required hint="Kept with the version.">
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
          </>
        )}
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="subtle" disabled={busy} onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || !test.name.trim() || (editing ? !reason.trim() : !code.trim())}
            onClick={() => void save()}>
            {busy ? "Saving…" : editing ? `Save as version ${editing.version + 1}` : "Add template"}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}

/** The library of tests a specification can be built from. */
export default function TestTemplates() {
  const { params, setFilters } = useUrlFilters();
  const q = params.get("q") ?? "";
  const list = useList<TestTemplateRow, Extras>("/api/test-templates/", { query: q ? { q } : {} });
  const [editing, setEditing] = useState<TestTemplateRow | null>(null);
  const [creating, setCreating] = useState(false);
  const canManage = list.data?.can_manage ?? false;

  return (
    <>
      <div className="page-head">
        <h1>Test templates</h1>
        <p className="sub">
          Tests the lab runs the same way each time. Each change is a new version, and a specification
          keeps the copy it was approved with.
        </p>
      </div>

      <ListCard
        title="Library"
        list={list}
        failure="Could not load the templates"
        emptyTitle="No templates yet"
        emptySub="Add the tests you use most, then build specifications from them."
        actions={canManage && <button className="primary small" onClick={() => setCreating(true)}>+ New template</button>}
        filters={<TextFilter label="Search" value={q} placeholder="Code, name or method" onChange={(text) => setFilters({ q: text })} />}
      >
        {(rows) => (
          <div className="table-wrap">
            <table className="grid">
              <thead><tr><th>Code</th><th>Test</th><th>Method</th><th>Limit</th><th>Version</th><th>Last change</th><th /></tr></thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.id} style={{ opacity: t.is_retired ? 0.55 : 1 }}>
                    <td className="num">{t.code}</td>
                    <td className="cell-title">
                      {t.name}
                      {t.is_retired && <span className="badge muted" style={{ marginLeft: 7 }}>retired</span>}
                    </td>
                    <td>{t.method || "—"}</td>
                    <td>{t.limit_text}</td>
                    <td className="num">v{t.version}</td>
                    <td>
                      {t.created_by}
                      <div className="cell-sub">{fmtDateTime(t.created_at)}</div>
                      {t.reason && <div className="cell-sub">“{t.reason}”</div>}
                    </td>
                    <td>{canManage && <button className="subtle small" onClick={() => setEditing(t)}>New version</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ListCard>

      {(creating || editing) && list.data && (
        <TemplateModal
          editing={editing}
          limitTypes={list.data.limit_types}
          onDone={() => void list.reload()}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
        />
      )}
    </>
  );
}
