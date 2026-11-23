import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiGet, apiPost } from "../../api";
import { EmptyState, Message, TableSkeleton } from "../../components/Feedback";
import Stamp from "../../components/Stamp";
import { useToast } from "../../components/Toast";
import type { LabAction, LabRecord } from "../../types";
import { ActionDialog, LabCellView } from "./LabParts";

/** One record of any register: what it says, its logs, its history and what can be done to it. */
export default function LabRecordPage() {
  const { register = "", id = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [record, setRecord] = useState<LabRecord | null>(null);
  const [error, setError] = useState("");
  const [acting, setActing] = useState<LabAction | null>(null);

  const load = useCallback(async () => {
    try {
      setRecord(await apiGet<LabRecord>(`/api/lab/${register}/${id}/`));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this record.");
    }
  }, [register, id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !record) {
    return (
      <>
        <div className="breadcrumb"><Link to={`/lab/${register}`}>Lab records</Link></div>
        <Message kind="error">{error}</Message>
      </>
    );
  }
  if (!record) return <div className="card"><div className="card-body flush"><TableSkeleton rows={6} /></div></div>;

  const facts = record.facts.filter((f) => f.value !== "" && f.value !== null);

  const act = async (action: LabAction, body: Record<string, unknown>) => {
    const next = await apiPost<LabRecord>(`/api/lab/${register}/${record.id}/${action.key}/`, body);
    setActing(null);
    toast("ok", action.done, next.title);
    // Drafting a new version lands on the new version.
    if (next.id !== record.id) navigate(`/lab/${register}/${next.id}`);
    else setRecord(next);
  };

  return (
    <>
      <div className="breadcrumb">
        <Link to="/lab">Lab records</Link> / <Link to={`/lab/${register}`}>{record.register_title}</Link> / {record.title}
      </div>
      <div className="page-head">
        <h1>{record.title}</h1>
        <p className="sub">
          {record.subtitle}{" "}
          {record.status && <span className={`badge ${record.status.tone}`}>{record.status.text}</span>}
        </p>
      </div>

      {record.notice && <div style={{ marginBottom: 16 }}><Message kind="warn">{record.notice}</Message></div>}

      <section className="card" aria-label="The record">
        <div className="card-head">
          <h2>The record</h2>
          <div className="spacer" />
          <div className="actions-bar">
            {record.actions.map((action) => (
              <button key={action.key} className={`${action.tone === "danger" ? "danger" : "ghost"} small`}
                onClick={() => setActing(action)}>
                {action.label}
              </button>
            ))}
          </div>
        </div>
        <div className="card-body doc-parts">
          <div className="kv">
            {facts.map((f) => (
              <div key={f.label}>
                <div className="k">{f.label}</div>
                <div className="v"><LabCellView cell={f.value} kind={f.kind} /></div>
              </div>
            ))}
          </div>
          {record.texts.map((t) => (
            <div key={t.label}>
              <div className="kv-label">{t.label}</div>
              <p className="kv-text">{t.text}</p>
            </div>
          ))}
        </div>
      </section>

      {record.tables.map((table) => (
        <section className="card" aria-label={table.heading} key={table.heading}>
          <div className="card-head"><h2>{table.heading}</h2></div>
          <div className="card-body flush">
            {table.rows.length === 0 ? (
              <EmptyState title={table.empty} />
            ) : (
              <div className="table-wrap">
                <table className="grid">
                  <thead>
                    <tr>{table.columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr>
                  </thead>
                  <tbody>
                    {table.rows.map((row, i) => (
                      <tr key={i}>
                        {table.columns.map((c) => (
                          <td key={c.key}><LabCellView cell={row[c.key]} kind={c.kind} /></td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>
      ))}

      <section className="card" aria-label="History">
        <div className="card-head"><h2>History</h2><span className="hint">Every change, with the old and new values</span></div>
        <div className="card-body">
          {record.history.length === 0 ? (
            <div className="cell-sub">Nothing recorded yet.</div>
          ) : (
            <ul className="timeline">
              {record.history.map((e) => (
                <li key={e.id}>
                  <span className="when"><Stamp at={e.at} /></span>
                  <span>
                    <b>{e.actor.name}</b> {e.what.toLowerCase()}
                    {e.changes.map((c) => (
                      <span className="comment" key={c.field}>
                        {c.field}: “{c.old || "blank"}” to “{c.new || "blank"}”
                      </span>
                    ))}
                    {e.comment && <span className="comment">“{e.comment}”</span>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {acting && (
        <ActionDialog action={acting} onSend={(body) => act(acting, body)} onClose={() => setActing(null)} />
      )}
    </>
  );
}
