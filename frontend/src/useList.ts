import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiGet } from "./api";
import type { Page, PeriodKey } from "./types";

export const PAGE_SIZES = [10, 25, 50, 100];
const DEFAULT_PAGE_SIZE = 25;

const isPageKey = (key: string) => key === "page" || key.endsWith("_page");

/**
 * Every filter and page number lives in the address bar, so a list survives
 * a refresh and the Back button, and a link can open it already filtered.
 */
export function useUrlFilters() {
  const [params, setParams] = useSearchParams();

  const setFilters = useCallback(
    (patch: Record<string, string>) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of Object.entries(patch)) {
            if (value) next.set(key, value);
            else next.delete(key);
          }
          // A different filter is a different list: start again at its first page.
          for (const key of [...next.keys()]) {
            if (isPageKey(key)) next.delete(key);
          }
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );

  return { params, setParams, setFilters };
}

/** A time with no zone is the lab's: the server reads it that way, so it is sent as picked. */
function toMoment(local: string) {
  return local;
}

export interface DateField {
  key: string;
  label: string;
}

/** The date filter of a page. One range can drive several lists. */
export function useDateRange({
  defaultPeriod = "all",
  fields = [],
}: {
  defaultPeriod?: PeriodKey;
  /** Which of the records' dates can be filtered on, where there is a choice. */
  fields?: DateField[];
} = {}) {
  const { params, setFilters } = useUrlFilters();
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const field = params.get("date_field") ?? fields[0]?.key ?? "";
  const custom = Boolean(from || to);
  const period = custom ? null : ((params.get("period") as PeriodKey | null) ?? defaultPeriod);

  const query: Record<string, string> = {};
  if (period) query.period = period;
  if (from) query.from = toMoment(from);
  if (to) query.to = toMoment(to);
  if (field) query.date_field = field;

  return {
    period,
    from,
    to,
    field,
    fields,
    /** What to send to the server. */
    query,
    search: new URLSearchParams(query).toString(),
    setPeriod: (key: PeriodKey) => setFilters({ period: key, from: "", to: "" }),
    setCustom: (nextFrom: string, nextTo: string) => setFilters({ period: "", from: nextFrom, to: nextTo }),
    /** Back to what this list shows by default. */
    clear: () => setFilters({ period: "", from: "", to: "" }),
    setField: (key: string) => setFilters({ date_field: key }),
  };
}

export type DateRange = ReturnType<typeof useDateRange>;

/**
 * One page of any list, keeping the difference between "loaded and empty"
 * and "failed to load" visible. A queue that silently renders empty after a
 * failed request would tell a checker there is no work waiting when there
 * is — so a failure must always show as a failure.
 *
 * `pageKey` names this list's page in the address bar, for a screen with
 * more than one list. It must be "page" or end in "_page".
 */
export function useList<T, Extra = unknown>(
  path: string,
  { query = {}, pageKey = "page" }: { query?: Record<string, string>; pageKey?: string } = {},
) {
  const { params, setParams, setFilters } = useUrlFilters();
  const asked = Math.max(Number(params.get(pageKey)) || 1, 1);
  const pageSize = Number(params.get("page_size")) || DEFAULT_PAGE_SIZE;
  const search = new URLSearchParams({ ...query, page: String(asked), page_size: String(pageSize) });
  const url = `${path}?${search.toString()}`;
  // The whole list under the same filters, every page of it, for a file.
  const exportUrl = `${path}?${new URLSearchParams(query).toString()}`;

  const [data, setData] = useState<(Page<T> & Extra) | null>(null);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  // Quick clicks can overtake each other: only the latest request may answer.
  const latest = useRef(0);

  const reload = useCallback(async () => {
    const ticket = ++latest.current;
    setLoading(true);
    try {
      const page = await apiGet<Page<T> & Extra>(url);
      if (ticket !== latest.current) return;
      setData(page);
      setError("");
    } catch (err) {
      if (ticket !== latest.current) return;
      setData(null);
      setError(err instanceof Error ? err.message : "Could not load.");
    }
    setLoaded(true);
    setLoading(false);
  }, [url]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const setPage = (page: number) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (page > 1) next.set(pageKey, String(page));
        else next.delete(pageKey);
        return next;
      },
      { replace: true },
    );

  return {
    /** The whole answer, for anything the list reports beyond its rows. */
    data,
    rows: data?.results ?? [],
    count: data?.count ?? 0,
    // The server's page, not the one asked for: a filter can shorten the list.
    page: data?.page ?? asked,
    pages: data?.pages ?? 1,
    pageSize,
    error,
    loaded,
    loading,
    reload,
    exportUrl,
    setPage,
    setPageSize: (size: number) => setFilters({ page_size: String(size) }),
  };
}

export type ListState<T> = ReturnType<typeof useList<T>>;
