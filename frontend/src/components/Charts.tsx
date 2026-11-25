import { useState } from "react";
import { Link } from "react-router-dom";

/**
 * Small charts, written against the design tokens.
 *
 * The bar charts are SINGLE-HUE on purpose: bar length carries the
 * magnitude, so colour never has to be told apart. That sidesteps the
 * colour-blindness problem entirely rather than mitigating it — and the one
 * blue used was checked for ≥3:1 contrast on both the light and dark card
 * surfaces. Pass/fail is shown as a labelled badge, never as colour alone.
 *
 * The donut needs several colours, so it never leans on them: every slice is
 * named in a legend beside it with its count and share, in the order it is
 * drawn, and the legend rows open the records behind each slice.
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

export interface DonutSlice {
  label: string;
  value: number;
  /** A colour token, such as "var(--pass)". */
  color: string;
  /** The records behind this slice. */
  to?: string;
}

const RADIUS = 46;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function share(value: number, total: number): string {
  if (!total || value <= 0) return "0%";
  const pct = (value / total) * 100;
  return pct < 1 ? "<1%" : `${Math.round(pct)}%`;
}

/**
 * A pie with a hole: how a whole divides into a few parts. The total (or a figure the caller
 * chooses, such as a pass rate) sits in the hole; pointing at a slice or its legend row shows
 * that part instead. A part of nothing is listed but not drawn, so a lab with no failures still
 * sees "Failed 0".
 */
export function DonutChart({
  slices,
  name,
  centerValue,
  centerLabel,
  emptyText = "Nothing to show yet.",
}: {
  slices: DonutSlice[];
  /** What is being divided, for people using a screen reader. */
  name: string;
  centerValue?: string | number;
  centerLabel?: string;
  emptyText?: string;
}) {
  const [active, setActive] = useState<number | null>(null);
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  const drawn = slices.filter((s) => s.value > 0).length;
  const gap = drawn > 1 ? 2.4 : 0;
  let cursor = 0;
  const arcs = slices.map((s) => {
    if (s.value <= 0 || total === 0) return null;
    const length = (s.value / total) * CIRCUMFERENCE;
    const arc = { length: Math.max(length - gap, 0.6), start: cursor + gap / 2 };
    cursor += length;
    return arc;
  });
  const chosen = active === null ? null : slices[active];
  const summary = `${name}: ${slices.map((s) => `${s.value} ${s.label.toLowerCase()}`).join(", ")}`;

  return (
    <div className={`donut${total === 0 ? " empty" : ""}`}>
      <div className="donut-ring">
        <svg viewBox="0 0 120 120" role="img" aria-label={summary}>
          <circle className="donut-track" cx="60" cy="60" r={RADIUS} />
          {slices.map((s, i) => {
            const arc = arcs[i];
            return arc && (
              <circle
                key={s.label}
                className={`donut-slice${active === i ? " on" : ""}`}
                cx="60" cy="60" r={RADIUS}
                stroke={s.color}
                strokeDasharray={`${arc.length} ${CIRCUMFERENCE - arc.length}`}
                strokeDashoffset={-arc.start}
                onMouseEnter={() => setActive(i)}
                onMouseLeave={() => setActive(null)}
              >
                <title>{`${s.label}: ${s.value} (${share(s.value, total)})`}</title>
              </circle>
            );
          })}
        </svg>
        <div className="donut-center" aria-hidden="true">
          <b>{chosen ? chosen.value : centerValue ?? total}</b>
          <span>{chosen ? `${chosen.label} · ${share(chosen.value, total)}` : centerLabel ?? "in total"}</span>
        </div>
      </div>
      {total === 0 ? (
        <p className="donut-empty">{emptyText}</p>
      ) : (
        <ul className="donut-legend">
          {slices.map((s, i) => {
            const row = (
              <>
                <i style={{ background: s.color }} aria-hidden="true" />
                <span className="donut-name">{s.label}</span>
                <b>{s.value}</b>
                <small>{share(s.value, total)}</small>
              </>
            );
            return (
              <li key={s.label} className={`${s.value === 0 ? "zero" : ""}${active === i ? " on" : ""}`}
                onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)}>
                {s.to
                  ? <Link to={s.to} className="donut-row" onFocus={() => setActive(i)} onBlur={() => setActive(null)}>{row}</Link>
                  : <div className="donut-row">{row}</div>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/**
 * Work held per person: the bar is what they hold, and the part of it already past its due date is
 * marked. Words beside every bar give the same two figures, so colour is never the only signal.
 */
export function WorkloadBars({
  rows,
  emptyText = "Nobody holds any work.",
}: {
  rows: { label: string; pending: number; overdue: number; to?: string }[];
  emptyText?: string;
}) {
  if (rows.length === 0) {
    return <div style={{ color: "var(--ink-3)", fontSize: 13, padding: "10px 0" }}>{emptyText}</div>;
  }
  const max = Math.max(1, ...rows.map((r) => r.pending));
  return (
    <div className="wl">
      {rows.map((r) => (
        <div className="wl-row" key={r.label}>
          <div className="wl-label">{r.to ? <Link to={r.to}>{r.label}</Link> : r.label}</div>
          <div className="wl-track" role="img" aria-label={`${r.pending} held, ${r.overdue} overdue`}>
            <span className="wl-late" style={{ width: `${(r.overdue / max) * 100}%` }} />
            <span className="wl-rest" style={{ width: `${((r.pending - r.overdue) / max) * 100}%` }} />
          </div>
          <div className="wl-value">
            <b>{r.pending}</b>
            {r.overdue > 0 && <small>{r.overdue} late</small>}
          </div>
        </div>
      ))}
    </div>
  );
}

const PIE_R = 90;

/** One slice of the pie, from `start` to `end` as shares of the whole, clockwise from twelve o'clock. */
function wedge(start: number, end: number) {
  const a0 = 2 * Math.PI * start - Math.PI / 2;
  const a1 = 2 * Math.PI * end - Math.PI / 2;
  const x0 = 100 + PIE_R * Math.cos(a0);
  const y0 = 100 + PIE_R * Math.sin(a0);
  const x1 = 100 + PIE_R * Math.cos(a1);
  const y1 = 100 + PIE_R * Math.sin(a1);
  return `M100,100L${x0.toFixed(2)},${y0.toFixed(2)}A${PIE_R},${PIE_R} 0 ${end - start > 0.5 ? 1 : 0} 1 ${x1.toFixed(2)},${y1.toFixed(2)}Z`;
}

/**
 * A pie: how a whole divides into a few parts, each slice carrying its share when it is wide enough to
 * hold it. The legend beside it names every part with its count and share, in the order the slices are
 * drawn, and opens the records behind each; pointing at either lifts the slice out.
 */
export function PieChart({ slices, name, emptyText = "Nothing to show yet." }: {
  slices: DonutSlice[];
  /** What is being divided, for people using a screen reader. */
  name: string;
  emptyText?: string;
}) {
  const [active, setActive] = useState<number | null>(null);
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  let cursor = 0;
  const parts = slices.map((s) => {
    if (s.value <= 0 || total === 0) return null;
    const start = cursor / total;
    cursor += s.value;
    return { start, end: cursor / total };
  });
  const summary = `${name}: ${slices.map((s) => `${s.value} ${s.label.toLowerCase()}`).join(", ")}`;

  return (
    <div className={`donut pie${total === 0 ? " empty" : ""}`}>
      <div className="pie-disc">
        <svg viewBox="0 0 200 200" role="img" aria-label={summary}>
          {total === 0 && <circle cx="100" cy="100" r={PIE_R} className="pie-none" />}
          {slices.map((s, i) => {
            const part = parts[i];
            if (!part) return null;
            const middle = 2 * Math.PI * ((part.start + part.end) / 2) - Math.PI / 2;
            const lift = active === i ? `translate(${(7 * Math.cos(middle)).toFixed(2)} ${(7 * Math.sin(middle)).toFixed(2)})` : undefined;
            const whole = part.end - part.start > 0.9999;
            return (
              <g key={s.label} transform={lift} onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)}>
                {whole
                  ? <circle cx="100" cy="100" r={PIE_R} fill={s.color} className="pie-slice" />
                  : <path d={wedge(part.start, part.end)} fill={s.color} className="pie-slice" />}
                <title>{`${s.label}: ${s.value} (${share(s.value, total)})`}</title>
              </g>
            );
          })}
          {slices.map((s, i) => {
            const part = parts[i];
            if (!part || part.end - part.start < 0.07) return null;
            const middle = 2 * Math.PI * ((part.start + part.end) / 2) - Math.PI / 2;
            const r = part.end - part.start > 0.9999 ? 0 : PIE_R * 0.6;
            const out = active === i ? 7 : 0;
            return (
              <text key={s.label} x={100 + (r + out) * Math.cos(middle)} y={100 + (r + out) * Math.sin(middle) + 4.5}
                textAnchor="middle" className="pie-label" aria-hidden="true">
                {share(s.value, total)}
              </text>
            );
          })}
        </svg>
      </div>
      {total === 0 ? (
        <p className="donut-empty">{emptyText}</p>
      ) : (
        <ul className="donut-legend">
          {slices.map((s, i) => {
            const row = (
              <>
                <i style={{ background: s.color }} aria-hidden="true" />
                <span className="donut-name">{s.label}</span>
                <b>{s.value}</b>
                <small>{share(s.value, total)}</small>
              </>
            );
            return (
              <li key={s.label} className={`${s.value === 0 ? "zero" : ""}${active === i ? " on" : ""}`}
                onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)}>
                {s.to
                  ? <Link to={s.to} className="donut-row" onFocus={() => setActive(i)} onBlur={() => setActive(null)}>{row}</Link>
                  : <div className="donut-row">{row}</div>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
