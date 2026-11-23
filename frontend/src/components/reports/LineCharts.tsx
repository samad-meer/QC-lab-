import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import type { ReportTimeline, ReportTrend } from "../../types";

/**
 * Change over time. These are the two charts that need a second colour, so
 * --chart-1 and --chart-2 are validated together, in both themes, for colour
 * blindness and against the card surface. Identity never rests on colour: each
 * line has a legend entry with its total and a label at its end. A failed point
 * is also a different shape, and every value is in the table under the chart.
 */

const HEIGHT = 210;
const LEFT = 34;
const TOP = 14;
const BOTTOM = 26;

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(entry.contentRect.width, 240)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

function dayLabel(date: string, unit: string) {
  const day = new Date(`${date}T00:00:00`);
  return unit === "month"
    ? day.toLocaleDateString("en-GB", { month: "short", year: "numeric" })
    : day.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

/** A round, even top for the axis, so that the tick halfway up is a whole number too. */
function niceMax(value: number) {
  if (value <= 4) return 4;
  const step = 10 ** Math.floor(Math.log10(value));
  const nice = [1, 2, 3, 4, 5, 6, 8, 10].map((n) => n * step).find((n) => n >= value && n % 2 === 0);
  return nice ?? value;
}

function compact(value: number) {
  return value >= 1000 ? `${value / 1000}K` : String(value);
}

/** One tooltip per chart, kept inside the plot. Series keys are short lines, values lead. */
function Tooltip({ x, width, title, rows }: {
  x: number;
  width: number;
  title: string;
  rows: { value: ReactNode; label: string; color: string }[];
}) {
  const left = Math.min(x + 12, width - 170);
  return (
    <div className="chart-tip" style={{ left: Math.max(left, 0) }} role="status">
      <div className="chart-tip-title">{title}</div>
      {rows.map((r) => (
        <div className="chart-tip-row" key={r.label}>
          <span className="chart-key" style={{ background: r.color }} aria-hidden="true" />
          <b>{r.value}</b>
          <span>{r.label}</span>
        </div>
      ))}
    </div>
  );
}

function Details({ children }: { children: ReactNode }) {
  return (
    <details className="chart-table">
      <summary>Show as a table</summary>
      <div className="table-wrap">{children}</div>
    </details>
  );
}

const SERIES = ["var(--chart-1)", "var(--chart-2)"];

/** Two counts over the same days, weeks or months. */
export function TimelineChart({ data, emptyText }: { data: ReportTimeline; emptyText: string }) {
  const { ref, width } = useWidth();
  const [active, setActive] = useState<number | null>(null);
  const { points, series, unit } = data;
  const total = points.reduce((sum, p) => sum + p.values[0] + p.values[1], 0);

  const right = 78;
  const plotW = Math.max(width - LEFT - right, 40);
  const plotH = HEIGHT - TOP - BOTTOM;
  const top = niceMax(Math.max(1, ...points.flatMap((p) => p.values)));
  const x = (i: number) => LEFT + (points.length > 1 ? (i / (points.length - 1)) * plotW : plotW / 2);
  const y = (v: number) => TOP + plotH - (v / top) * plotH;
  const ticks = [0, top / 2, top];
  const labelEvery = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(plotW / 70))));
  const last = points[points.length - 1];

  // Labels at the end of each line, moved apart if the lines end together.
  const ends = series.map((_, s) => y(last?.values[s] ?? 0));
  if (Math.abs(ends[0] - ends[1]) < 14) {
    const middle = (ends[0] + ends[1]) / 2;
    const [upper, lower] = ends[0] <= ends[1] ? [0, 1] : [1, 0];
    ends[upper] = middle - 7;
    ends[lower] = middle + 7;
  }

  const hover = (clientX: number, rect: DOMRect) => {
    const position = ((clientX - rect.left - LEFT) / plotW) * (points.length - 1);
    setActive(Math.min(Math.max(Math.round(position), 0), points.length - 1));
  };

  if (total === 0) return <div className="chart-empty">{emptyText}</div>;
  const shown = active === null ? null : points[active];

  return (
    <div>
      <div className="chart-legend">
        {series.map((name, s) => (
          <span key={name}>
            <i className="chart-key" style={{ background: SERIES[s] }} aria-hidden="true" />
            {name} <b>{points.reduce((sum, p) => sum + p.values[s], 0)}</b>
          </span>
        ))}
      </div>
      <div className="chart-frame" ref={ref}>
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={`${series.join(" and ")} over time. The table below the chart has every value.`}
          tabIndex={0}
          onPointerMove={(e) => hover(e.clientX, e.currentTarget.getBoundingClientRect())}
          onPointerLeave={() => setActive(null)}
          onFocus={() => setActive(points.length - 1)}
          onBlur={() => setActive(null)}
          onKeyDown={(e) => {
            if (e.key === "ArrowLeft") setActive((a) => Math.max((a ?? 0) - 1, 0));
            if (e.key === "ArrowRight") setActive((a) => Math.min((a ?? 0) + 1, points.length - 1));
          }}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={LEFT} x2={LEFT + plotW} y1={y(t)} y2={y(t)} className="chart-grid" />
              <text x={LEFT - 8} y={y(t) + 4} textAnchor="end" className="chart-axis">{compact(t)}</text>
            </g>
          ))}
          {points.map((p, i) => (i === points.length - 1 || (i % labelEvery === 0 && x(points.length - 1) - x(i) >= 64)) && (
            <text key={p.date} x={x(i)} y={HEIGHT - 8} textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"} className="chart-axis">
              {dayLabel(p.date, unit)}
            </text>
          ))}
          {series.map((name, s) => (
            <polyline
              key={name}
              fill="none"
              stroke={SERIES[s]}
              strokeWidth="2"
              strokeLinejoin="round"
              strokeLinecap="round"
              points={points.map((p, i) => `${x(i)},${y(p.values[s])}`).join(" ")}
            />
          ))}
          {active !== null && (
            <line x1={x(active)} x2={x(active)} y1={TOP} y2={TOP + plotH} className="chart-cross" />
          )}
          {series.map((name, s) => {
            const at = active ?? points.length - 1;
            return (
              <circle key={name} cx={x(at)} cy={y(points[at].values[s])} r="4" fill={SERIES[s]} className="chart-dot" />
            );
          })}
          {series.map((name, s) => (
            <text key={name} x={LEFT + plotW + 10} y={ends[s] + 4} className="chart-end">{name}</text>
          ))}
        </svg>
        {shown && active !== null && (
          <Tooltip
            x={x(active)}
            width={width}
            title={dayLabel(shown.date, unit)}
            rows={series.map((name, s) => ({ value: shown.values[s], label: name, color: SERIES[s] }))}
          />
        )}
      </div>
      <Details>
        <table className="grid">
          <thead>
            <tr>
              <th>{unit === "day" ? "Day" : unit === "week" ? "Week starting" : "Month"}</th>
              {series.map((name) => <th key={name}>{name}</th>)}
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.date}>
                <td>{dayLabel(p.date, unit)}</td>
                {p.values.map((v, s) => <td key={series[s]} className="num">{v}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </Details>
    </div>
  );
}

/**
 * One test over time, against its limits. Points are evenly spaced in the order
 * they were tested: batches are not made on a schedule, and the sequence is
 * what a trend is read from. Each point opens the sample behind it.
 */
export function TrendChart({ trend }: { trend: ReportTrend }) {
  const { ref, width } = useWidth();
  const navigate = useNavigate();
  const [active, setActive] = useState<number | null>(null);
  const { points, low, high } = trend;

  const right = 16;
  const plotW = Math.max(width - LEFT - 18 - right, 40);
  const left = LEFT + 18;
  const plotH = HEIGHT - TOP - BOTTOM;
  const values = [...points.map((p) => p.y), ...[low, high].filter((v): v is number => v !== null)];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const margin = (max - min) * 0.08 || Math.max(Math.abs(max) * 0.05, 1);
  const bottom = min - margin;
  const top = max + margin;
  const x = (i: number) => left + (points.length > 1 ? (i / (points.length - 1)) * plotW : plotW / 2);
  const y = (v: number) => TOP + plotH - ((v - bottom) / (top - bottom)) * plotH;
  const shown = active === null ? null : points[active];

  return (
    <div className="trend">
      <div className="trend-head">
        <b>{trend.heading}</b>
        <span className="hint">{trend.sub}</span>
      </div>
      <div className="chart-frame" ref={ref}>
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={`${trend.heading} over ${points.length} results. The table below the chart has every value.`}
          onPointerLeave={() => setActive(null)}
        >
          {[low, high].map((limit, n) => limit !== null && (
            <g key={n}>
              <line x1={left} x2={left + plotW} y1={y(limit)} y2={y(limit)} className="chart-limit" />
              <text x={left + 4} y={y(limit) - 4} className="chart-axis">{n === 0 ? "Lower" : "Upper"} limit {limit}</text>
            </g>
          ))}
          <text x={left - 8} y={y(max) + 4} textAnchor="end" className="chart-axis">{max}</text>
          <text x={left - 8} y={y(min) + 4} textAnchor="end" className="chart-axis">{min}</text>
          <polyline
            fill="none"
            stroke="var(--chart-1)"
            strokeWidth="2"
            strokeLinejoin="round"
            strokeLinecap="round"
            points={points.map((p, i) => `${x(i)},${y(p.y)}`).join(" ")}
          />
          {active !== null && <line x1={x(active)} x2={x(active)} y1={TOP} y2={TOP + plotH} className="chart-cross" />}
          {points.map((p, i) => (
            p.outcome === "FAIL" ? (
              <rect key={i} x={x(i) - 4.5} y={y(p.y) - 4.5} width="9" height="9" fill="var(--fail)" className="chart-dot" />
            ) : (
              <circle key={i} cx={x(i)} cy={y(p.y)} r="4" fill="var(--chart-1)" className="chart-dot" />
            )
          ))}
          <text x={left} y={HEIGHT - 8} className="chart-axis">{points[0].label.slice(0, 11)}</text>
          {points.length > 1 && (
            <text x={left + plotW} y={HEIGHT - 8} textAnchor="end" className="chart-axis">
              {points[points.length - 1].label.slice(0, 11)}
            </text>
          )}
          {points.map((p, i) => (
            <circle
              key={i}
              cx={x(i)}
              cy={y(p.y)}
              r="12"
              fill="transparent"
              className="chart-hit"
              tabIndex={0}
              role={p.to ? "link" : "img"}
              aria-label={`${p.text}, batch ${p.batch}, ${p.outcome}, ${p.label}`}
              style={p.to ? undefined : { cursor: "default" }}
              onPointerEnter={() => setActive(i)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
              onClick={() => { if (p.to) navigate(p.to); }}
              onKeyDown={(e) => { if (e.key === "Enter" && p.to) navigate(p.to); }}
            />
          ))}
        </svg>
        {shown && active !== null && (
          <Tooltip
            x={x(active)}
            width={width}
            title={shown.label}
            rows={[
              {
                value: shown.text, label: shown.outcome === "FAIL" ? "Failed" : "Result",
                color: shown.outcome === "FAIL" ? "var(--fail)" : "var(--chart-1)",
              },
              { value: shown.batch, label: "Batch", color: "transparent" },
              { value: shown.spec, label: "Specification", color: "transparent" },
            ]}
          />
        )}
      </div>
      <Details>
        <table className="grid">
          <thead>
            <tr><th>Date</th><th>Batch</th><th>Sample</th><th>Spec</th><th>Result</th><th>Pass/fail</th></tr>
          </thead>
          <tbody>
            {points.map((p, i) => (
              <tr key={i}>
                <td>{p.label}</td>
                <td>{p.batch}</td>
                <td>{p.sample}</td>
                <td>{p.spec}</td>
                <td className="num">{p.text}</td>
                <td><span className={`badge ${p.outcome === "FAIL" ? "fail" : p.outcome === "PASS" ? "pass" : "muted"}`}>{p.outcome}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Details>
    </div>
  );
}
