import { useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { DashboardInsights, EquipmentGroup, FailureRow, ReportTimeline } from "../types";
import { Details, Tooltip, compact, dayLabel, niceMax, useWidth } from "./reports/LineCharts";

/**
 * The dashboard's bigger charts. One rule for all of them: a figure opens the records it counts, and
 * every value is reachable without a pointer, through the keyboard, the table under the chart, or both.
 *
 * Marks are thin (24px at most), the top of a column is rounded and its foot is square, parts of one
 * column are 2px apart, and the grid is a hairline. Colour follows meaning: red is late or failed,
 * green is passed, teal is plain magnitude, grey is what has not happened yet.
 */

const HEIGHT = 220;
const LEFT = 34;
const TOP = 16;
const BOTTOM = 40;
const MAX_BAR = 24;
const GAP = 2;

export interface ColumnPart { name: string; value: number; color: string }
export interface Column {
  key: string;
  label: string;
  /** A second line under the label, such as the date under a weekday. */
  sub?: string;
  parts: ColumnPart[];
  to?: string;
  /** Drawn in bold: today. */
  strong?: boolean;
  /** Rows to add to the tooltip beyond the parts, such as a pass rate. */
  extra?: { value: string; label: string }[];
  tip?: string;
}

/** A bar with its top corners rounded and its foot square, so it grows from the baseline. */
function topRounded(x: number, y: number, w: number, h: number, r: number) {
  const radius = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + radius}Q${x},${y} ${x + radius},${y}H${x + w - radius}Q${x + w},${y} ${x + w},${y + radius}V${y + h}Z`;
}

function Swatch({ color }: { color: string }) {
  return <i className="chart-swatch" style={{ background: color }} aria-hidden="true" />;
}

/**
 * Columns along one baseline. Each column is one hit target taller than its mark: hover or focus shows
 * what it counts, and a click opens the records. Arrow keys move along them.
 */
export function Columns({ columns, name, emptyText, separators = [], legend, thin = false }: {
  columns: Column[];
  name: string;
  emptyText: string;
  /** Hairlines between groups, as column indexes the line comes before. */
  separators?: number[];
  legend?: ReactNode;
  /** Few, wide columns, such as a histogram, may be thicker than a calendar's. */
  thin?: boolean;
}) {
  const { ref, width } = useWidth();
  const navigate = useNavigate();
  const [active, setActive] = useState<number | null>(null);

  const total = columns.reduce((sum, c) => sum + c.parts.reduce((s, p) => s + p.value, 0), 0);
  if (total === 0) return <div className="chart-empty">{emptyText}</div>;

  const plotW = Math.max(width - LEFT - 6, 60);
  const plotH = HEIGHT - TOP - BOTTOM;
  const sums = columns.map((c) => c.parts.reduce((s, p) => s + p.value, 0));
  const top = niceMax(Math.max(1, ...sums));
  const slot = plotW / columns.length;
  const barW = Math.min(thin ? 18 : MAX_BAR + 8, Math.max(slot - 6, 4));
  const y = (v: number) => TOP + plotH - (v / top) * plotH;
  const labelWidth = Math.max(...columns.map((c) => Math.max(c.label.length, (c.sub ?? "").length))) * 6 + 8;
  const every = Math.max(1, Math.ceil(labelWidth / slot));
  const peak = sums.indexOf(Math.max(...sums));
  const shown = active === null ? null : columns[active];
  const centre = (i: number) => LEFT + slot * i + slot / 2;

  const move = (e: KeyboardEvent) => {
    if (e.key === "ArrowLeft") setActive((a) => Math.max((a ?? 1) - 1, 0));
    else if (e.key === "ArrowRight") setActive((a) => Math.min((a ?? -1) + 1, columns.length - 1));
    else if (e.key === "Enter" && active !== null && columns[active].to) navigate(columns[active].to as string);
    else if (e.key === "Escape") setActive(null);
  };

  return (
    <div>
      {legend && <div className="chart-legend">{legend}</div>}
      <div className="chart-frame" ref={ref}>
        <svg width={width} height={HEIGHT} role="img" tabIndex={0}
          aria-label={`${name}. The table below the chart has every value; arrow keys move along the columns.`}
          onPointerLeave={() => setActive(null)} onFocus={() => setActive((a) => a ?? peak)} onBlur={() => setActive(null)}
          onKeyDown={move}>
          {[0, top / 2, top].map((t) => (
            <g key={t}>
              <line x1={LEFT} x2={LEFT + plotW} y1={y(t)} y2={y(t)} className="chart-grid" />
              <text x={LEFT - 8} y={y(t) + 4} textAnchor="end" className="chart-axis">{compact(t)}</text>
            </g>
          ))}
          {separators.map((i) => (
            <line key={`s${i}`} x1={LEFT + slot * i} x2={LEFT + slot * i} y1={TOP} y2={TOP + plotH + 6} className="chart-sep" />
          ))}
          {columns.map((c, i) => {
            let floor = 0;
            const parts = c.parts.filter((p) => p.value > 0);
            return (
              <g key={c.key} className={active === i ? "col on" : "col"}>
                {parts.map((p, n) => {
                  const base = y(floor);
                  floor += p.value;
                  const height = Math.max(base - y(floor) - (n > 0 ? GAP : 0), 2);
                  const x = centre(i) - barW / 2;
                  const last = n === parts.length - 1;
                  return last
                    ? <path key={p.name} d={topRounded(x, base - height, barW, height, 4)} fill={p.color} />
                    : <rect key={p.name} x={x} y={base - height} width={barW} height={height} fill={p.color} />;
                })}
                {i === peak && sums[i] > 0 && (
                  <text x={centre(i)} y={y(sums[i]) - 6} textAnchor="middle" className="chart-peak">{sums[i]}</text>
                )}
                {i % every === 0 && (
                  <text x={centre(i)} textAnchor="middle" className={`chart-axis${c.strong ? " strong" : ""}`}>
                    <tspan x={centre(i)} y={HEIGHT - BOTTOM + 15}>{c.label}</tspan>
                    {c.sub && <tspan x={centre(i)} y={HEIGHT - BOTTOM + 29}>{c.sub}</tspan>}
                  </text>
                )}
                <rect x={LEFT + slot * i} y={TOP} width={slot} height={plotH + 6} fill="transparent"
                  className="chart-hit" role={c.to ? "link" : "img"}
                  aria-label={`${c.tip ?? [c.label, c.sub].filter(Boolean).join(" ")}: ${c.parts.map((p) => `${p.value} ${p.name.toLowerCase()}`).join(", ")}`}
                  style={c.to ? undefined : { cursor: "default" }}
                  onPointerEnter={() => setActive(i)} onPointerMove={() => setActive(i)}
                  onClick={() => { if (c.to) navigate(c.to); }} />
              </g>
            );
          })}
        </svg>
        {shown && active !== null && (
          <Tooltip x={centre(active)} width={width} title={shown.tip ?? [shown.label, shown.sub].filter(Boolean).join(" ")}
            rows={[
              ...shown.parts.map((p) => ({ value: p.value, label: p.name, color: p.color })),
              ...(shown.extra ?? []).map((e) => ({ value: e.value, label: e.label, color: "transparent" })),
            ]} />
        )}
      </div>
      <Details>
        <table className="grid">
          <thead>
            <tr><th>{name}</th>{columns[0].parts.map((p) => <th key={p.name}>{p.name}</th>)}</tr>
          </thead>
          <tbody>
            {columns.map((c) => (
              <tr key={c.key}>
                <td>{c.tip ?? [c.label, c.sub].filter(Boolean).join(" ")}</td>
                {c.parts.map((p) => <td key={p.name} className="num">{p.value}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </Details>
    </div>
  );
}

/** Passed and failed results, for each day, week or month of the period. */
export function ResultsByPeriod({ data }: { data: ReportTimeline }) {
  const columns: Column[] = data.points.map((p) => {
    const [passed, failed] = p.values;
    return {
      key: p.date, label: dayLabel(p.date, data.unit),
      parts: [{ name: "Passed", value: passed, color: "var(--pass)" }, { name: "Failed", value: failed, color: "var(--fail)" }],
      extra: passed + failed > 0 ? [{ value: `${Math.round((100 * passed) / (passed + failed))}%`, label: "Pass rate" }] : [],
    };
  });
  const passed = data.points.reduce((n, p) => n + p.values[0], 0);
  const failed = data.points.reduce((n, p) => n + p.values[1], 0);
  return (
    <Columns columns={columns} name="Results entered" emptyText="No results were entered in this period." thin
      legend={<>
        <span><Swatch color="var(--pass)" />Passed <b>{passed}</b></span>
        <span><Swatch color="var(--fail)" />Failed <b>{failed}</b></span>
      </>} />
  );
}

const WEEKDAY = new Intl.DateTimeFormat("en-GB", { weekday: "short" });
const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });

/** What falls due over the next two weeks, with what is already late standing apart on the left. */
export function DueOutlook({ outlook }: { outlook: DashboardInsights["outlook"] }) {
  const columns: Column[] = [
    {
      key: "late", label: "Late", tip: "Already late",
      parts: [{ name: "Past their due date", value: outlook.overdue.value, color: "var(--fail)" }],
      to: outlook.overdue.value > 0 ? outlook.overdue.to : undefined,
    },
    ...outlook.days.map((d, i): Column => {
      const day = new Date(`${d.date}T00:00:00`);
      return {
        key: d.date, label: i === 0 ? "Today" : WEEKDAY.format(day), sub: DATE.format(day).replace(" ", " "),
        strong: i === 0, tip: `${WEEKDAY.format(day)} ${DATE.format(day)}`,
        parts: [{ name: "Due", value: d.value, color: "var(--chart-1)" }],
        to: d.value > 0 ? d.to : undefined,
      };
    }),
    {
      key: "later", label: "Later", tip: "Due after these two weeks",
      parts: [{ name: "Due later", value: outlook.later.value, color: "var(--chart-6)" }],
      to: outlook.later.value > 0 ? outlook.later.to : undefined,
    },
  ];
  return (
    <Columns columns={columns} name="Open samples by due date" emptyText="Nothing in the lab has a due date." separators={[1, columns.length - 1]}
      legend={<>
        <span><Swatch color="var(--fail)" />Already late <b>{outlook.overdue.value}</b></span>
        <span><Swatch color="var(--chart-1)" />Due in the next two weeks <b>{outlook.days.reduce((n, d) => n + d.value, 0)}</b></span>
        <span><Swatch color="var(--chart-6)" />Later <b>{outlook.later.value}</b></span>
      </>} />
  );
}

/** How long release took, in bands. */
export function TurnaroundSpread({ data }: { data: DashboardInsights["turnaround"] }) {
  const columns: Column[] = data.bands.map((b) => ({
    key: b.label, label: b.label, tip: `${b.label} days`,
    parts: [{ name: "Samples released", value: b.value, color: "var(--chart-1)" }],
  }));
  const released = data.on_time + data.late;
  return (
    <div className="turn">
      <div className="turn-head">
        <div><b>{data.mean === null ? "–" : `${data.mean.toFixed(1)}d`}</b><span>average, receipt to release</span></div>
        <div><b>{released ? `${Math.round((100 * data.on_time) / released)}%` : "–"}</b><span>released by their due date</span></div>
        <Link to={data.to} className="turn-link">Open the report →</Link>
      </div>
      <Columns columns={columns} name="Days from receipt to release" emptyText="Nothing was released in this period." thin />
      {released > 0 && <div className="chart-caption">Days from receipt to release</div>}
      {released > 0 && (
        <div className="turn-meter" role="img" aria-label={`${data.on_time} released by their due date, ${data.late} late`}>
          <span style={{ flexGrow: data.on_time, background: "var(--pass)" }} title={`${data.on_time} on time`} />
          <span style={{ flexGrow: data.late, background: "var(--fail)" }} title={`${data.late} late`} />
        </div>
      )}
      {released > 0 && (
        <div className="chart-legend">
          <span><Swatch color="var(--pass)" />On time <b>{data.on_time}</b></span>
          <span><Swatch color="var(--fail)" />Late <b>{data.late}</b></span>
        </div>
      )}
    </div>
  );
}

/** The ramp for how long samples have waited: the older, the darker. One hue, so it reads as "more of the same". */
const AGE_STEPS = [28, 52, 76, 100];

/** Samples in the lab, by where they are and how long they have been there. */
export function Ageing({ data }: { data: DashboardInsights["ageing"] }) {
  const totals = data.stages.map((s) => s.values.reduce((a, b) => a + b, 0));
  const most = Math.max(1, ...totals);
  if (totals.every((t) => t === 0)) return <div className="chart-empty">Nothing is waiting in the lab.</div>;
  const shade = (i: number) => `color-mix(in srgb, var(--chart-1) ${AGE_STEPS[Math.min(i, AGE_STEPS.length - 1)]}%, var(--surface))`;
  return (
    <div>
      <div className="chart-legend">
        {data.bands.map((b, i) => <span key={b.key}><Swatch color={shade(i)} />{b.label}</span>)}
      </div>
      <div className="age">
        {data.stages.map((s, row) => (
          <div className="age-row" key={s.key}>
            <span className="age-label">{s.label}</span>
            <div className="age-track">
              {s.values.map((v, i) => v > 0 && (
                <Link key={data.bands[i].key} to={s.links[i]} className="age-seg"
                  style={{ width: `${(v / most) * 100}%`, background: shade(i) }}
                  aria-label={`${s.label}, ${data.bands[i].label}: ${v} ${v === 1 ? "sample" : "samples"}`}
                  data-tip={`${data.bands[i].label} · ${v} ${v === 1 ? "sample" : "samples"}`}>
                  {(v / most) * 100 > 6 && <span className={i >= 2 ? "light" : ""}>{v}</span>}
                </Link>
              ))}
            </div>
            <b className="age-total">{totals[row]}</b>
          </div>
        ))}
      </div>
      <Details>
        <table className="grid">
          <thead><tr><th>Stage</th>{data.bands.map((b) => <th key={b.key}>{b.label}</th>)}</tr></thead>
          <tbody>
            {data.stages.map((s) => <tr key={s.key}><td>{s.label}</td>{s.values.map((v, i) => <td key={i} className="num">{v}</td>)}</tr>)}
          </tbody>
        </table>
      </Details>
    </div>
  );
}

/** The tests, or the products, that failed most, each against everything entered for it. */
export function Failures({ rows, empty }: { rows: FailureRow[]; empty: string }) {
  if (rows.length === 0) return <div className="chart-empty">{empty}</div>;
  const most = Math.max(...rows.map((r) => r.failed));
  return (
    <ol className="rank">
      {rows.map((r) => (
        <li key={r.label}>
          <Link to={r.to} className="rank-row">
            <span className="rank-label">{r.label}</span>
            <span className="rank-track"><i style={{ width: `${Math.max((r.failed / most) * 100, 3)}%` }} /></span>
            <span className="rank-value"><b>{r.failed}</b> <small>of {r.total} · {r.rate}%</small></span>
          </Link>
        </li>
      ))}
    </ol>
  );
}

const STATE_COLOR: Record<string, string> = {
  ok: "var(--pass)", soon: "var(--warn)", late: "var(--fail)", out: "var(--chart-6)", held: "var(--chart-6)",
};

/** Whether the instruments, or the standards and reagents, are in date. */
export function EquipmentHealth({ group }: { group: EquipmentGroup }) {
  const total = group.rows.reduce((n, r) => n + r.value, 0);
  return (
    <div className="equip">
      <div className="equip-head"><Link to={group.to}>Open the register →</Link></div>
      {total === 0 ? <div className="chart-empty">None are recorded yet.</div> : (
        <>
          <div className="equip-bar" role="img" aria-label={group.rows.map((r) => `${r.value} ${r.label.toLowerCase()}`).join(", ")}>
            {group.rows.map((r) => r.value > 0 && <span key={r.key} style={{ flexGrow: r.value, background: STATE_COLOR[r.key] }} title={`${r.label}: ${r.value}`} />)}
          </div>
          <ul className="equip-rows">
            {group.rows.map((r) => (
              <li key={r.key} className={r.value === 0 ? "zero" : ""}>
                <Swatch color={STATE_COLOR[r.key]} />
                <span>{r.label}</span>
                <b>{r.value}</b>
                <small>{Math.round((100 * r.value) / total)}%</small>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
