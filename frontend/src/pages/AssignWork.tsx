import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../api";
import Avatar from "../components/Avatar";
import BulkAssignModal from "../components/execution/BulkAssignModal";
import { Message } from "../components/Feedback";
import LineIcon from "../components/LineIcon";
import ListCard from "../components/list/ListCard";
import SampleFilters, { useSampleFilters } from "../components/SampleFilters";
import SampleTable from "../components/SampleTable";
import type { PersonRef, SampleListItem, Tasks } from "../types";
import { useList, useUrlFilters } from "../useList";

interface Holder extends PersonRef {
  role: string;
  is_me: boolean;
  sections: string[];
  /** Samples they hold whose testing can still change hands. */
  open: number;
  late: number;
}

interface Overview {
  open: number;
  late: number;
  people: Holder[];
}

/** Testing can change hands until the analyst signs: received, or in testing. */
const OPEN = "RECEIVED,IN_TESTING";

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/**
 * Giving testing out: who holds how much, and the samples that can still change hands. Tick
 * some, choose the analyst, and each goes through the same checks as on its own page.
 */
export default function AssignWork() {
  const { params, setFilters } = useUrlFilters();
  const analyst = /^\d+$/.test(params.get("analyst") ?? "") ? params.get("analyst")! : "";
  const filters = useSampleFilters();
  const list = useList<SampleListItem>("/api/samples/", { query: { ...filters.query, status: OPEN, ...(analyst ? { analyst } : {}) } });
  const [overview, setOverview] = useState<Overview | null>(null);
  const [declined, setDeclined] = useState(0);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<Set<number>>(() => new Set());
  const [assigning, setAssigning] = useState<number[] | null>(null);

  const loadOverview = useCallback(() => {
    apiGet<Overview>("/api/assign/overview/").then(setOverview).catch((e) => setError(e instanceof Error ? e.message : "Could not load who holds what."));
    apiGet<Tasks>("/api/tasks/?counts=1").then((t) => setDeclined(t.counts.needs_reassigning)).catch(() => undefined);
  }, []);
  useEffect(() => {
    loadOverview();
  }, [loadOverview]);

  const choose = (id: number | null) => setFilters({ analyst: id === null || String(id) === analyst ? "" : String(id) });
  const holders = overview?.people.filter((p) => p.open > 0 || p.sections.length > 0) ?? [];
  const most = Math.max(1, ...holders.map((p) => p.open));
  const chosen = holders.find((p) => String(p.id) === analyst);

  return (
    <>
      <div className="page-head">
        <h1>Assign work</h1>
        <p className="sub">
          Who holds what, and the samples whose testing can still change hands. Tick samples, choose the analyst, and
          each is assigned as it would be on its own page, with the same checks and a notice to the analyst.
        </p>
      </div>

      {error && <Message kind="error">{error}</Message>}
      {declined > 0 && (
        <Message kind="warn">
          <b>{plural(declined, "piece of work")} {declined === 1 ? "was" : "were"} declined</b> and nobody holds
          {declined === 1 ? " it" : " them"} now.{" "}
          <Link to="/tasks#needs_reassigning">Open them in My tasks →</Link>
        </Message>
      )}

      <section className="aw-people" aria-label="Who holds what">
        <button type="button" className={`aw-person all${analyst ? "" : " on"}`} aria-pressed={!analyst} onClick={() => choose(null)}>
          <span className="aw-all-icon"><LineIcon name="people" size={20} /></span>
          <span className="aw-who">
            <b>Everyone</b>
            <small>{overview ? `${plural(holders.length, "analyst")}` : "Loading…"}</small>
          </span>
          <span className="aw-count">
            <b>{overview?.open ?? "–"}</b>
            <small>open</small>
          </span>
          {overview && overview.late > 0 && <span className="badge fail aw-late">{overview.late} late</span>}
        </button>
        {holders.map((p) => (
          <button type="button" key={p.id} className={`aw-person${String(p.id) === analyst ? " on" : ""}`}
            aria-pressed={String(p.id) === analyst} onClick={() => choose(p.id)}
            title={`Show the ${plural(p.open, "sample")} ${p.name} holds`}>
            <Avatar name={p.name} size={36} />
            <span className="aw-who">
              <b>{p.name}{p.is_me ? " (you)" : ""}</b>
              <small>{p.sections.length ? `Trained for ${p.sections.join(", ")}` : "Holds work, trained for no section"}</small>
            </span>
            <span className="aw-count">
              <b>{p.open}</b>
              <small>open</small>
            </span>
            <span className="aw-bar" aria-hidden="true"><i style={{ width: `${(100 * p.open) / most}%` }} /></span>
            {p.late > 0 && <span className="badge fail aw-late">{p.late} late</span>}
          </button>
        ))}
      </section>

      <ListCard
        title={chosen ? `${chosen.name}'s open samples` : "Open samples"}
        hint="Received or in testing"
        list={list}
        failure="Could not load samples"
        emptyTitle={chosen ? `${chosen.name} holds no open samples` : "No open samples"}
        emptySub="Samples appear here once they are received, until their analyst signs the results."
        filters={<SampleFilters filters={filters} />}
      >
        {(rows) => (
          <>
            {picked.size > 0 && (
              <div className="bulk-bar" role="region" aria-label="Selected samples">
                <b>{picked.size} selected</b>
                <button className="primary small" onClick={() => setAssigning([...picked])}>
                  <LineIcon name="people" size={15} /> Assign testing to…
                </button>
                <button className="link-btn" onClick={() => setPicked(new Set())}>Clear</button>
              </div>
            )}
            <SampleTable samples={rows} selection={{
              can: () => true,
              selected: picked,
              onChange: setPicked,
            }} />
          </>
        )}
      </ListCard>

      {assigning && (
        <BulkAssignModal
          ids={assigning}
          onDone={() => {
            setPicked(new Set());
            void list.reload();
            loadOverview();
          }}
          onClose={() => setAssigning(null)}
        />
      )}
    </>
  );
}
