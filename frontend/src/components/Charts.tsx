import { Link } from "react-router-dom";

/**
 * Small charts, written against the design tokens.
 *
 * Every chart here is SINGLE-HUE on purpose: bar length carries the
 * magnitude, so colour never has to be told apart. That sidesteps the
 * colour-blindness problem entirely rather than mitigating it — and the one
 * blue used was checked for ≥3:1 contrast on both the light and dark card
 * surfaces. Pass/fail is shown as a labelled badge, never as colour alone.
 */

export interface BarDatum {
  label: string;
  value: number;
  /** Optional second line under the label. */
  sub?: string;
  /** The records behind this bar. */
  to?: string;
}

export function BarList({
  data,
  emptyText = "Nothing in this period.",
  unit = "",
}: {
  data: BarDatum[];
  emptyText?: string;
  unit?: string;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  if (data.length === 0) {
    return <div style={{ color: "var(--ink-3)", fontSize: 13, padding: "10px 0" }}>{emptyText}</div>;
  }
  return (
    <div className="barlist">
      {data.map((d) => (
        <div className="barlist-row" key={d.label}>
          <div className="barlist-label">
            {d.to ? <Link to={d.to}>{d.label}</Link> : d.label}
            {d.sub && <div className="cell-sub">{d.sub}</div>}
          </div>
          <div className="barlist-track">
            <div
              className="barlist-fill"
              style={{ width: `${Math.max((d.value / max) * 100, d.value > 0 ? 2 : 0)}%` }}
            />
          </div>
          <div className="barlist-value">
            {d.value}
            {unit}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Activity per day. One series, so no legend is needed — the title names it. */
export function ColumnChart({
  data,
  height = 116,
}: {
  data: { date: string; count: number }[];
  height?: number;
}) {
  if (data.length === 0) {
    return (
      <div style={{ color: "var(--ink-3)", fontSize: 13, padding: "18px 0" }}>
        No activity recorded in this period.
      </div>
    );
  }
  const max = Math.max(1, ...data.map((d) => d.count));
  // Label only the ends when the run is long — a label per column collides.
  const labelEvery = data.length <= 8 ? 1 : Math.ceil(data.length / 6);

  return (
    <div className="colchart" style={{ height }}>
      {data.map((d, i) => {
        const day = new Date(`${d.date}T00:00:00`);
        const label = day.toLocaleDateString(undefined, { day: "numeric", month: "short" });
        return (
          <div className="colchart-col" key={d.date} title={`${label}: ${d.count} events`}>
            <div className="colchart-count">{d.count > 0 ? d.count : ""}</div>
            <div
              className="colchart-bar"
              style={{ height: `${Math.max((d.count / max) * 100, d.count > 0 ? 3 : 0)}%` }}
            />
            <div className="colchart-tick">{i % labelEvery === 0 ? label : ""}</div>
          </div>
        );
      })}
    </div>
  );
}

/**
 * A single ratio against a limit — a meter, not a two-slice pie.
 * The number is always shown, so the fill is reinforcement, not the message.
 */
export function Meter({
  value,
  max = 100,
  caption,
  tone = "brand",
}: {
  value: number;
  max?: number;
  caption: string;
  tone?: "brand" | "fail";
}) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div>
      <div className="meter-track">
        <div
          className="meter-fill"
          style={{
            width: `${pct}%`,
            background: tone === "fail" ? "var(--fail)" : "var(--chart-1)",
          }}
        />
      </div>
      <div style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 6 }}>{caption}</div>
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  alert = false,
}: {
  label: string;
  value: string | number;
  sub?: string;
  alert?: boolean;
}) {
  return (
    <div className={`stat ${alert ? "alert" : ""}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}
