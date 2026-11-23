import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, NavLink, useNavigate, useParams } from "react-router-dom";
import { apiGet, apiPost } from "../../api";
import { Message, TableSkeleton } from "../../components/Feedback";
import ListCard from "../../components/list/ListCard";
import TextFilter from "../../components/list/TextFilter";
import { useToast } from "../../components/Toast";
import type { LabRecord, LabRegister, LabRow } from "../../types";
import { useList, useUrlFilters } from "../../useList";
import { FieldGrid, initialValues, LabCellView } from "./LabParts";

function AddForm({ register, onCancel }: { register: LabRegister; onCancel: () => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [values, setValues] = useState(() => initialValues(register.add_fields));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await apiPost<LabRecord>(`/api/lab/${register.key}/`, values);
      toast("ok", `${created.title} recorded`);
      navigate(`/lab/${register.key}/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
      setBusy(false);
    }
  };

  return (
    <section className="card" aria-label={register.add_label}>
      <div className="card-head">
        <h2>{register.add_label}</h2>
        {register.add_hint && <span className="hint">{register.add_hint}</span>}
      </div>
      <div className="card-body">
        <form className="stack" onSubmit={(e) => void submit(e)}>
          {error && <Message kind="error">{error}</Message>}
          <FieldGrid fields={register.add_fields} values={values}
            onChange={(key, value) => setValues((v) => ({ ...v, [key]: value }))} />
          <div className="actions-bar" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="subtle" onClick={onCancel}>Cancel</button>
            <button type="submit" className="primary" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
          </div>
        </form>
      </div>
    </section>
  );
}

function RegisterList({ register }: { register: LabRegister }) {
  const navigate = useNavigate();
  const { params, setFilters } = useUrlFilters();
  const q = params.get("q") ?? "";
  const query: Record<string, string> = q ? { q } : {};
  for (const filter of register.filters) {
    const value = params.get(filter.key);
    if (value) query[filter.key] = value;
  }
  const list = useList<LabRow>(`/api/lab/${register.key}/`, { query });
  const [adding, setAdding] = useState(false);

  return (
    <>
      {adding && <AddForm register={register} onCancel={() => setAdding(false)} />}
      <ListCard
        title={register.title}
        exportable
        hint={list.loaded && !list.error ? `${list.count} on record` : undefined}
        list={list}
        failure={`Could not load ${register.title.toLowerCase()}`}
        emptyTitle="Nothing matches"
        emptySub={register.note}
        actions={register.can_add && !adding ? (
          <button className="primary small" onClick={() => setAdding(true)}>+ {register.add_label}</button>
        ) : undefined}
        filters={(
          <>
            <div className="report-filters">
              {register.search_hint && (
                <TextFilter label="Search" value={q} placeholder={register.search_hint}
                  onChange={(text) => setFilters({ q: text })} />
              )}
              {register.filters.map((f) => (
                <label className="field" key={f.key}>
                  {f.label}
                  <select value={params.get(f.key) ?? ""} onChange={(e) => setFilters({ [f.key]: e.target.value })}>
                    <option value="">All</option>
                    {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </label>
              ))}
            </div>
            {register.note && <span className="cell-sub">{register.note}</span>}
          </>
        )}
      >
        {(rows) => (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>{register.columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="clickable" tabIndex={0} onClick={() => navigate(row.to)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") navigate(row.to);
                    }}>
                    {register.columns.map((c) => (
                      <td key={c.key}><LabCellView cell={row.cells[c.key]} kind={c.kind} /></td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ListCard>
    </>
  );
}

/** What each register is for, so "Lab records" opens on the whole picture rather than on its first tab. */
function Overview({ registers }: { registers: LabRegister[] }) {
  return (
    <div className="report-directory">
      {registers.map((r) => (
        <section className="card" key={r.key} aria-label={r.title}>
          <div className="card-head">
            <div>
              <h2>{r.title}</h2>
              <span className="hint">
                {r.count === 0 ? `No ${r.singular}s yet` : `${r.count} ${r.singular}${r.count === 1 ? "" : "s"}`}
              </span>
            </div>
          </div>
          <div className="card-body" style={{ display: "grid", gap: 8 }}>
            <p style={{ margin: 0 }}>{r.description}</p>
            <p className="cell-sub" style={{ margin: 0 }}>{r.purpose}</p>
            <div className="actions-bar" style={{ marginTop: 4 }}>
              <Link to={`/lab/${r.key}`} className="btn-link">Open {r.title} →</Link>
              {r.can_add && <span className="hint">You can add these</span>}
            </div>
          </div>
        </section>
      ))}
    </div>
  );
}

/** Every lab register, one screen: what each holds and how it reads comes from the server. */
export default function LabRegisterPage() {
  const { register: key } = useParams();
  const [registers, setRegisters] = useState<LabRegister[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setRegisters((await apiGet<{ registers: LabRegister[] }>("/api/lab/registers/")).registers);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the lab records.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <Message kind="error">{error}</Message>;
  if (!registers) return <div className="card"><div className="card-body flush"><TableSkeleton /></div></div>;
  const current = registers.find((r) => r.key === key);
  if (key && !current) return <Navigate to="/lab" replace />;

  return (
    <>
      <div className="page-head">
        <h1>Lab records</h1>
        <p className="sub">
          {current
            ? current.description
            : "The records behind every result: the instruments, standards and methods used, who is qualified to "
              + "use them, the samples kept after testing, and planned changes to how the lab works."}
        </p>
      </div>
      <nav className="step-tabs" aria-label="Registers">
        <NavLink to="/lab" end className={({ isActive }) => `step-tab ${isActive ? "on" : ""}`}
          style={{ padding: "9px 14px", textDecoration: "none" }}>
          <b>Overview</b>
        </NavLink>
        {registers.map((r) => (
          <NavLink key={r.key} to={`/lab/${r.key}`} className={({ isActive }) => `step-tab ${isActive ? "on" : ""}`}
            style={{ padding: "9px 14px", textDecoration: "none" }}>
            <b>{r.title}</b>
          </NavLink>
        ))}
      </nav>
      {current ? <RegisterList key={current.key} register={current} /> : <Overview registers={registers} />}
    </>
  );
}
