import { useEffect, useRef, useState } from "react";
import type { PeriodKey } from "../../types";
import type { DateRange } from "../../useList";

const PERIODS: { key: PeriodKey; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "week", label: "This week" },
  { key: "lastweek", label: "Last week" },
  { key: "month", label: "This month" },
  { key: "lastmonth", label: "Last month" },
  { key: "quarter", label: "Last 90 days" },
  { key: "all", label: "All time" },
];

/** Time to wait after typing in a date, so each keystroke does not reload the list. */
const SETTLE_MS = 400;

/**
 * The one date control: a named period, or any from and to, to the minute.
 * Whichever is chosen goes through useDateRange to the server, which decides
 * what falls inside it.
 */
export default function DateRangeFilter({ range }: { range: DateRange }) {
  const [from, setFrom] = useState(range.from);
  const [to, setTo] = useState(range.to);
  const settling = useRef<number | undefined>(undefined);

  // Follow the address bar when it changes: the Back button, or a period chosen.
  useEffect(() => {
    setFrom(range.from);
    setTo(range.to);
  }, [range.from, range.to]);

  useEffect(() => () => window.clearTimeout(settling.current), []);

  const type = (nextFrom: string, nextTo: string) => {
    setFrom(nextFrom);
    setTo(nextTo);
    window.clearTimeout(settling.current);
    settling.current = window.setTimeout(() => range.setCustom(nextFrom, nextTo), SETTLE_MS);
  };

  const forget = () => {
    window.clearTimeout(settling.current);
    setFrom("");
    setTo("");
  };

  const pick = (key: PeriodKey) => {
    forget();
    range.setPeriod(key);
  };

  const clear = () => {
    forget();
    range.clear();
  };

  return (
    <div className="range-filter">
      <div className="period-tabs" role="group" aria-label="Time range">
        {PERIODS.map((p) => (
          <button key={p.key} type="button" aria-pressed={p.key === range.period} onClick={() => pick(p.key)}>
            {p.label}
          </button>
        ))}
      </div>
      {range.fields.length > 1 && (
        <label className="range-field">
          Filter by
          <select value={range.field} onChange={(e) => range.setField(e.target.value)}>
            {range.fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
          </select>
        </label>
      )}
      <label className="range-field">
        From
        <input type="datetime-local" value={from} max={to || undefined} onChange={(e) => type(e.target.value, to)} />
      </label>
      <label className="range-field">
        To
        <input type="datetime-local" value={to} min={from || undefined} onChange={(e) => type(from, e.target.value)} />
      </label>
      {(from || to) && (
        <button type="button" className="subtle small" onClick={clear}>Clear dates</button>
      )}
    </div>
  );
}
