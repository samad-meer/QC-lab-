import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import BatchModal from "../components/BatchModal";
import DateRangeFilter from "../components/list/DateRangeFilter";
import ListCard from "../components/list/ListCard";
import TextFilter from "../components/list/TextFilter";
import { useToast } from "../components/Toast";
import type { BatchRow } from "../types";
import { useDateRange, useList, useUrlFilters } from "../useList";
import { fmtDate } from "../util";

const DATE_FIELDS = [
  { key: "registered", label: "Date recorded" },
  { key: "manufactured", label: "Date of manufacture" },
  { key: "expiry", label: "Expiry date" },
];

export default function Batches() {
  const { can } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const { params, setFilters } = useUrlFilters();
  const range = useDateRange({ fields: DATE_FIELDS });
  const q = params.get("q") ?? "";
  const product = params.get("product") ?? "";
  const list = useList<BatchRow>("/api/batches/", {
    query: { ...range.query, ...(q && { q }), ...(product && { product }) },
  });
  const [creating, setCreating] = useState(false);

  return (
    <>
      <div className="page-head">
        <h1>Batches</h1>
        <p className="sub">
          Each batch ties a product to its samples, results and certificates. The official number is
          kept exactly as assigned; the internal ID is the system's own.
        </p>
      </div>

      <ListCard
        title="All batches"
        exportable
        hint={list.loaded && !list.error ? `${list.count} on record` : undefined}
        list={list}
        failure="Could not load batches"
        emptyTitle="No batches match these filters"
        emptySub="A batch is recorded the first time one of its samples is registered."
        actions={
          <div className="actions-bar">
            {product && (
              <button className="subtle small" onClick={() => setFilters({ product: "" })}>Showing one product ✕</button>
            )}
            {can("batch.manage") && (
              <button className="primary small" onClick={() => setCreating(true)}>+ New batch</button>
            )}
          </div>
        }
        filters={
          <>
            <DateRangeFilter range={range} />
            <TextFilter label="Search" value={q} placeholder="Official number, internal ID or product"
              onChange={(text) => setFilters({ q: text })} />
          </>
        }
      >
        {(rows) => (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Official batch no</th><th>Internal ID</th><th>Product</th>
                  <th title="Manufacturing site: where the batch was made, when it is recorded">Site</th>
                  <th>Manufactured</th><th>Expiry</th><th>Samples</th>
                  <th title="The version of its product's QC stages the batch goes through, kept from when it was created">
                    Stages version
                  </th>
                  <th>QC stages</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((b) => (
                  <tr key={b.id} className="clickable" tabIndex={0} onClick={() => navigate(`/batches/${b.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") navigate(`/batches/${b.id}`);
                    }}>
                    <td className="cell-title">{b.official_batch_no}</td>
                    <td className="num">{b.internal_id}</td>
                    <td>
                      <div className="cell-title">{b.product.name}</div>
                      <div className="cell-sub">{b.product.code}</div>
                    </td>
                    <td>{b.manufacturing_site || "—"}</td>
                    <td>{b.manufacturing_date ? fmtDate(b.manufacturing_date) : "—"}</td>
                    <td>{b.expiry_date ? fmtDate(b.expiry_date) : "—"}</td>
                    <td className="num">{b.sample_count}</td>
                    <td>
                      {b.stage_plan ? (
                        <>
                          <span className="tag">v{b.stage_plan.version}</span>
                          {b.stage_plan.latest > b.stage_plan.version && (
                            <div className="cell-sub" title={`Batches created now go through version ${b.stage_plan.latest}; this one keeps the version it was created with.`}>
                              current is v{b.stage_plan.latest}
                            </div>
                          )}
                        </>
                      ) : (
                        <span className="cell-sub" title="Created before its product had QC stages">—</span>
                      )}
                    </td>
                    <td>
                      {b.qc_progress ? (
                        <>
                          <span className={`badge ${b.qc_progress.failed ? "fail"
                            : b.qc_progress.required > 0 && b.qc_progress.passed === b.qc_progress.required ? "pass" : "muted"}`}>
                            {b.qc_progress.passed} of {b.qc_progress.required} passed
                          </span>
                          {b.qc_progress.failed && <div className="cell-sub">A required stage failed</div>}
                        </>
                      ) : (
                        <span className="cell-sub">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ListCard>

      {creating && (
        <BatchModal
          onDone={(batch) => {
            toast("ok", `Batch ${batch.internal_id} recorded`);
            navigate(`/batches/${batch.id}`);
          }}
          onClose={() => setCreating(false)}
        />
      )}
    </>
  );
}
