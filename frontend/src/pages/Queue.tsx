import ListCard from "../components/list/ListCard";
import SampleFilters, { useSampleFilters } from "../components/SampleFilters";
import SampleTable from "../components/SampleTable";
import type { SampleListItem } from "../types";
import { useList } from "../useList";

export default function Queue() {
  const filters = useSampleFilters();
  // The backend defaults the list to the caller's queue: samples waiting at
  // a review stage their role signs, in whatever workflow they belong to.
  const list = useList<SampleListItem>("/api/samples/", { query: filters.query });

  return (
    <>
      <div className="page-head">
        <h1>Awaiting my signature</h1>
        <p className="sub">
          Certificates waiting at a review stage your role signs. Each result is shown next to its
          allowed limit — sign, or send it back to the analyst with a comment.
        </p>
      </div>
      <ListCard
        title="Ready for you"
        hint={list.loaded && !list.error ? `${list.count} waiting` : undefined}
        list={list}
        failure="Could not load your queue"
        emptyTitle="Your queue is clear"
        emptySub="Nothing is waiting for your signature right now."
        filters={<SampleFilters filters={filters} />}
      >
        {(rows) => <SampleTable samples={rows} />}
      </ListCard>
    </>
  );
}
