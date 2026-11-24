import { Link } from "react-router-dom";
import AuditReviews from "../../components/AuditReviews";
import DateRangeFilter from "../../components/list/DateRangeFilter";
import ListCard from "../../components/list/ListCard";
import TextFilter from "../../components/list/TextFilter";
import type { AuditRow } from "../../types";
import { useDateRange, useList, useUrlFilters } from "../../useList";
import { fmtDateTime } from "../../util";

const SEVERITY_ICON: Record<string, string> = {
  signature: "✓",
  refused: "!",
  attention: "↩",
  admin: "⚙",
  normal: "•",
  quiet: "·",
};

export default function AuditTrail() {
  const { params, setFilters } = useUrlFilters();
  const action = params.get("action") ?? "";
  const actor = params.get("actor") ?? "";
  const entityId = params.get("entity_id") ?? "";
  const notableOnly = params.get("notable") === "1";
  const overridesOnly = params.get("override") === "1";

  const range = useDateRange({ defaultPeriod: "week" });
  const query: Record<string, string> = { ...range.query };
  if (action) query.action = action;
  if (actor) query.actor = actor;
  if (entityId) query.entity_id = entityId;
  if (notableOnly) query.notable = "1";
  if (overridesOnly) query.override = "1";
  const list = useList<AuditRow, { actions: string[] }>("/api/auth/audit/", { query });

  return (
    <>
      <div className="page-head">
        <h1>Activity log</h1>
        <p className="sub">
          Who did what, when, and from where — including every attempt the system refused.
          These records can never be edited or deleted by anyone, including an administrator.
        </p>
      </div>

      <AuditReviews />

      <ListCard
        title="Events"
        exportable
        list={list}
        failure="Could not load the activity log"
        emptyTitle="Nothing matches"
        emptySub="Try a wider time range or clear the filters."
        skeletonRows={6}
        actions={
          <>
            <button
              className={overridesOnly ? "primary small" : "ghost small"}
              onClick={() => setFilters({ override: overridesOnly ? "" : "1" })}
            >
              {overridesOnly ? "✓ " : ""}Only administrator overrides
            </button>
            <button
              className={notableOnly ? "primary small" : "ghost small"}
              onClick={() => setFilters({ notable: notableOnly ? "" : "1" })}
            >
              {notableOnly ? "✓ " : ""}Only refusals &amp; corrections
            </button>
          </>
        }
        filters={
          <>
            <DateRangeFilter range={range} />
            <div className="form-row three">
              <label className="field">
                Action
                <select value={action} onChange={(e) => setFilters({ action: e.target.value })}>
                  <option value="">All actions</option>
                  {(list.data?.actions ?? []).map((a) => (
                    <option key={a} value={a}>{a.replaceAll("_", " ").toLowerCase()}</option>
                  ))}
                </select>
              </label>
              <TextFilter label="Who" value={actor} placeholder="username"
                onChange={(v) => setFilters({ actor: v })} />
              <TextFilter label="Record" value={entityId} placeholder="sample no, username…"
                onChange={(v) => setFilters({ entity_id: v })} />
            </div>
          </>
        }
      >
        {(rows) => (
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th style={{ width: "15%" }}>When</th>
                    <th style={{ width: "14%" }}>Who</th>
                    <th>What happened</th>
                    <th style={{ width: "11%" }}>Record</th>
                    <th style={{ width: "10%" }}>From</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((e) => (
                    <tr key={e.id}>
                      <td style={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                        {fmtDateTime(e.at)}
                      </td>
                      <td>
                        <div className="cell-title">{e.actor_name}</div>
                        <div className="cell-sub mono">{e.actor}</div>
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
                          <span
                            className={`feed-dot ${e.severity}`}
                            aria-hidden="true"
                            style={{ width: 20, height: 20, fontSize: 10 }}
                          >
                            {SEVERITY_ICON[e.severity] ?? "•"}
                          </span>
                          <span>
                            {e.sentence}
                            <div className="cell-sub mono">{e.action}</div>
                          </span>
                        </div>
                      </td>
                      <td>
                        {e.sample_no ? (
                          <span className="mono">{e.sample_no}</span>
                        ) : (
                          <span className="mono">{e.entity_id}</span>
                        )}
                        <div className="cell-sub">{e.entity}</div>
                      </td>
                      <td className="mono">{e.ip_address || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
        )}
      </ListCard>

      <p style={{ fontSize: 12.5, color: "var(--ink-3)" }}>
        Looking for trends rather than individual events? See{" "}
        <Link to="/admin/analytics">lab analytics</Link>.
      </p>
    </>
  );
}
