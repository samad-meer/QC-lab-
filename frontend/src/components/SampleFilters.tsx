import { useDateRange, useUrlFilters } from "../useList";
import DateRangeFilter from "./list/DateRangeFilter";
import TextFilter from "./list/TextFilter";
import { SAMPLE_DATE_FIELDS } from "./SampleTable";

/** The filters of any list of samples. One set can drive several lists on a page. */
export function useSampleFilters() {
  const range = useDateRange({ fields: SAMPLE_DATE_FIELDS });
  const { params, setFilters } = useUrlFilters();
  const q = params.get("q") ?? "";
  return {
    range,
    q,
    setSearch: (text: string) => setFilters({ q: text }),
    /** What to send to the server. */
    query: q ? { ...range.query, q } : range.query,
  };
}

export default function SampleFilters({ filters }: { filters: ReturnType<typeof useSampleFilters> }) {
  return (
    <>
      <DateRangeFilter range={filters.range} />
      <TextFilter
        label="Search"
        value={filters.q}
        placeholder="Sample number, batch, reference or product"
        onChange={filters.setSearch}
      />
    </>
  );
}
