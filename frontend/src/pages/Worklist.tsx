import { Message } from "../components/Feedback";
import ListCard from "../components/list/ListCard";
import SampleFilters, { useSampleFilters } from "../components/SampleFilters";
import SampleTable from "../components/SampleTable";
import type { SampleListItem } from "../types";
import { useList } from "../useList";

export default function Worklist() {
  const filters = useSampleFilters();
  const open = useList<SampleListItem, { overdue: number }>("/api/samples/", {
    query: { ...filters.query, status: "RECEIVED,IN_TESTING", mine: "1" },
    pageKey: "open_page",
  });
  const later = useList<SampleListItem>("/api/samples/", {
    query: { ...filters.query, status: "IN_REVIEW,APPROVED" },
    pageKey: "later_page",
  });
  const overdue = open.data?.overdue ?? 0;

  return (
    <>
      <div className="page-head">
        <h1>My worklist</h1>
        <p className="sub">
          Samples assigned to you. Enter each result against its limit — the system decides pass
          or fail — then sign the certificate.
        </p>
      </div>

      {overdue > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Message kind="warn">
            <b>{overdue} sample{overdue > 1 ? "s are" : " is"} past the due date.</b>
          </Message>
        </div>
      )}

      <div className="card">
        <div className="list-filters"><SampleFilters filters={filters} /></div>
      </div>

      <ListCard
        title="To test"
        hint={open.loaded && !open.error ? `${open.count} open` : undefined}
        list={open}
        failure="Could not load your worklist"
        emptyTitle="No samples waiting"
        emptySub="Nothing is waiting for you to test in this date range."
      >
        {(rows) => <SampleTable samples={rows} highlight={() => true} />}
      </ListCard>

      <ListCard
        title="Signed and onward"
        hint={later.loaded && !later.error ? String(later.count) : undefined}
        list={later}
        failure="Could not load your signed samples"
        emptyTitle="Nothing signed yet"
        emptySub="Samples you have signed will stay here so you can follow their progress."
        skeletonRows={2}
      >
        {(rows) => <SampleTable samples={rows} />}
      </ListCard>
    </>
  );
}
