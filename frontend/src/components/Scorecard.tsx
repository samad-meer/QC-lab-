import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type {
  AnalystScore, LimitRow, ProductScore, ReportTimeline, ScoreGauge, ScoreStatus, Scorecard as ScorecardData, SectionRate,
} from "../types";
import { DonutChart } from "./Charts";
import type { DonutSlice } from "./Charts";
import { Columns, Ranked } from "./InsightCharts";
import { dayLabel } from "./reports/LineCharts";
import type { Column } from "./InsightCharts";
import { Sparkline } from "./KpiStrip";

/**
 * The scorecard: dials, a table with a light and a trend on every row, the failure rate by section, and the
 * limits the lab has to stay within. A light is never colour alone: each status is a shape as well (a circle,
 * a diamond, a triangle) and is said aloud. The colours are a reading guide for the screen, not a promise the
 * lab has made: what the lab promises is each sample's own due date, which the limits panel counts.
 */

const STATUS_WORDS: Record<ScoreStatus, string> = {
  good: "Within the reading guide", warn: "Near the limit of the reading guide", bad: "Below the reading guide", none: "Nothing to judge",
};
const LOAD_WORDS: Record<ScoreStatus, string> = {
  good: "Nothing overdue", warn: "A quarter or less is overdue", bad: "More than a quarter is overdue", none: "Nothing open",
};

function Light({ status, words }: { status: ScoreStatus; words: Record<ScoreStatus, string> }) {
  return <span className={`light ${status}`} role="img" aria-label={words[status]} title={words[status]} />;
}

// --- the dials -----------------------------------------------------------------

const CX = 100;
const CY = 98;
const R = 76;

/** The dial starts here: a pass rate below half is not a reading anyone needs spread over the dial. */
const FLOOR = 50;

/** A point on the dial for a figure from FLOOR to 100, from its left end to its right end. */
function onDial(value: number, radius = R): [number, number] {
  const share = Math.min(Math.max((value - FLOOR) / (100 - FLOOR), 0), 1);
  const angle = Math.PI * (1 - share);
  return [CX + radius * Math.cos(angle), CY - radius * Math.sin(angle)];
}

function band(from: number, to: number) {
  const [x1, y1] = onDial(from);
  const [x2, y2] = onDial(to);
  return `M${x1.toFixed(2)},${y1.toFixed(2)}A${R},${R} 0 0 1 ${x2.toFixed(2)},${y2.toFixed(2)}`;
}

const GAUGE_WORDS: Record<ScoreStatus, string> = {
  good: "At or above the guide", warn: "Near the guide", bad: "Below the guide", none: "Nothing to read",
};

/** A speedometer: red, amber and green stretches, a needle on the figure, and the level where green begins. */
export function Gauge({ gauge }: { gauge: ScoreGauge }) {
  const [good, warn] = gauge.reference;
  const value = gauge.value;
  const [nx, ny] = onDial(value ?? 0, R - 26);
  const [tx, ty] = onDial(good, R + 15);
  const [t1, t2] = [onDial(good, R - 12), onDial(good, R + 9)];
  return (
    <Link to={gauge.to} className={`dial ${gauge.status}`}
      aria-label={`${gauge.label}: ${value === null ? "nothing to read" : `${value}%`}. Green from ${good}%, amber from ${warn}%. ${gauge.sub}.`}>
      <svg viewBox="0 0 200 138" className="dial-svg" aria-hidden="true">
        <path d={band(FLOOR, 100)} className="dial-track" />
        <path d={band(FLOOR + 0.4, warn - 0.4)} stroke="var(--fail)" className="dial-band" />
        <path d={band(warn + 0.4, good - 0.4)} stroke="var(--chart-2)" className="dial-band" />
        <path d={band(good + 0.4, 99.6)} stroke="var(--pass)" className="dial-band" />
        <line x1={t1[0]} y1={t1[1]} x2={t2[0]} y2={t2[1]} className="dial-mark" />
        <text x={tx} y={ty + 3} textAnchor="middle" className="dial-tick">{good}</text>
        <text x={CX - R} y={CY + 18} textAnchor="middle" className="dial-tick">{FLOOR}</text>
        <text x={CX + R} y={CY + 18} textAnchor="middle" className="dial-tick">100</text>
        {value !== null && <line x1={CX} y1={CY} x2={nx} y2={ny} className="dial-needle" />}
        <circle cx={CX} cy={CY} r="8" className="dial-hub" />
        <circle cx={CX} cy={CY} r="3" className="dial-pin" />
        <text x={CX} y={CY + 38} textAnchor="middle" className="dial-value">{value === null ? "–" : `${Math.round(value)}%`}</text>
      </svg>
      <b className="dial-label">{gauge.label}</b>
      <span className="dial-sub">{gauge.sub}</span>
      <span className={`dial-state ${gauge.status}`}><Light status={gauge.status} words={GAUGE_WORDS} />{GAUGE_WORDS[gauge.status]}</span>
    </Link>
  );
}

// --- the table -----------------------------------------------------------------

const dash = (n: number | null, unit = "") => (n === null ? "–" : `${n}${unit}`);

function Cell({ to, children, opt = false }: { to?: string; children: ReactNode; opt?: boolean }) {
  return <td className={`num${opt ? " opt" : ""}`}>{to ? <Link to={to}>{children}</Link> : children}</td>;
}

function ProductTable({ rows }: { rows: ProductScore[] }) {
  return (
    <div className="table-wrap">
      <table className="grid score-table">
        <thead>
          <tr>
            <th>Product</th>
            <th className="num opt" title="Samples received in the period">Received</th>
            <th className="num" title="Results entered in the period">Results</th>
            <th className="num" title="Share of those results that passed">Pass rate</th>
            <th className="num opt" title="Share released by their due date">On time</th>
            <th className="num opt" title="Average days from receipt to release">Avg days</th>
            <th className="opt-s" title="The pass rate over the period">Trend</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td><Link to={r.to} className="score-name"><b>{r.label}</b><small>{r.code}</small></Link></td>
              <Cell to={r.received ? r.to_received : undefined} opt>{r.received}</Cell>
              <Cell to={r.results ? r.to_results : undefined}>{r.results}</Cell>
              <td className="num"><span className="score-rate"><Light status={r.status} words={STATUS_WORDS} />{dash(r.pass_rate === null ? null : Math.round(r.pass_rate), "%")}</span></td>
              <td className="num opt">{dash(r.on_time === null ? null : Math.round(r.on_time), "%")}</td>
              <td className="num opt">{dash(r.turnaround, "d")}</td>
              <td className="opt-s"><Sparkline values={r.spark} tone="var(--chart-4)" className="score-spark" /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AnalystTable({ rows }: { rows: AnalystScore[] }) {
  return (
    <div className="table-wrap">
      <table className="grid score-table">
        <thead>
          <tr>
            <th>Analyst</th><th className="num" title="Open samples, with a light for how much of it is overdue">Open</th>
            <th className="num">Overdue</th><th className="num opt">Released</th>
            <th className="num opt" title="Share released by their due date">On time</th>
            <th className="num opt" title="Average days from receipt to release">Avg days</th><th className="opt-s" title="Samples released over the period">Trend</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td><Link to={r.to} className="score-name"><b>{r.label}</b></Link></td>
              <td className="num"><span className="score-rate"><Light status={r.status} words={LOAD_WORDS} />{r.open}</span></td>
              <td className="num">{r.overdue}</td>
              <td className="num opt">{r.completed}</td>
              <td className="num opt">{dash(r.on_time === null ? null : Math.round(r.on_time), "%")}</td>
              <td className="num opt">{dash(r.turnaround, "d")}</td>
              <td className="opt-s"><Sparkline values={r.spark} tone="var(--chart-4)" className="score-spark" zero /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** How each product's results went, or what each analyst holds, a light and a trend to the row. */
export function PerformanceTable({ card }: { card: ScorecardData }) {
  const [by, setBy] = useState<"products" | "analysts">("products");
  const analysts = card.analysts;
  const showing = by === "analysts" && analysts ? "analysts" : "products";
  return (
    <div>
      <div className="score-head">
        {analysts ? (
          <div className="seg" role="group" aria-label="Group the table by">
            <button type="button" className={showing === "products" ? "on" : ""} aria-pressed={showing === "products"} onClick={() => setBy("products")}>By product</button>
            <button type="button" className={showing === "analysts" ? "on" : ""} aria-pressed={showing === "analysts"} onClick={() => setBy("analysts")}>By analyst</button>
          </div>
        ) : <span />}
        <span className="score-key">
          {showing === "products" ? (
            <>
              <Light status="good" words={STATUS_WORDS} /> {card.reference.pass_rate.good}% or more passed
              <Light status="warn" words={STATUS_WORDS} /> {card.reference.pass_rate.warn}–{card.reference.pass_rate.good}%
              <Light status="bad" words={STATUS_WORDS} /> below
            </>
          ) : (
            <>
              <Light status="good" words={LOAD_WORDS} /> nothing overdue
              <Light status="warn" words={LOAD_WORDS} /> a quarter or less
              <Light status="bad" words={LOAD_WORDS} /> more
            </>
          )}
        </span>
      </div>
      {showing === "products"
        ? (card.products.length ? <ProductTable rows={card.products} /> : <div className="chart-empty">Nothing was received or tested in this period.</div>)
        : (analysts && analysts.length ? <AnalystTable rows={analysts} /> : <div className="chart-empty">Nobody holds open work.</div>)}
      {showing === "analysts" && <p className="score-note">For planning the work, not for ranking people.</p>}
    </div>
  );
}

// --- the section chart, the ranking, the limits ----------------------------------

/** The share of each section's results that failed, a figure on every column and the highest one marked. */
export function SectionRates({ rows }: { rows: SectionRate[] }) {
  if (rows.length === 0) return <div className="chart-empty">No results were entered in this period.</div>;
  const worst = Math.max(...rows.map((r) => r.rate));
  const columns: Column[] = rows.map((r) => ({
    key: r.label, label: r.code || r.label, tip: r.label,
    parts: [{
      name: "Results failed", value: r.rate, display: `${r.rate}%`,
      color: r.rate === worst && worst > 0 ? "var(--chart-4)" : "var(--chart-2)",
    }],
    extra: [{ value: `${r.failed} of ${r.total}`, label: "results" }],
    to: r.failed > 0 ? r.to : undefined,
  }));
  return (
    <Columns columns={columns} name="Share of results that failed, by section" emptyText="" showZero valueLabels
      format={(n) => `${Number.isInteger(n) ? n : n.toFixed(1)}%`}
      legend={<span>The highest is marked in blue. A column opens the failed results it counts.</span>} />
  );
}

/** What release took for each product, slowest first. */
export function TurnaroundRanking({ rows }: { rows: ProductScore[] }) {
  const ranked = rows.filter((r) => r.turnaround !== null).sort((a, b) => (b.turnaround as number) - (a.turnaround as number));
  return (
    <Ranked tone="var(--chart-2)" empty="Nothing was released in this period."
      rows={ranked.map((r) => ({
        label: r.label, amount: r.turnaround as number,
        text: <><b>{r.turnaround}d</b> <small>{r.completed} released</small></>,
        to: r.completed ? r.to_released : undefined,
      }))} />
  );
}

/** What has to stay inside its limit, each a share with the ones outside it a click away. */
export function Limits({ rows }: { rows: LimitRow[] }) {
  return (
    <ul className="limits">
      {rows.map((r) => {
        const inside = r.total - r.outside;
        const percent = r.total === 0 ? null : Math.round((100 * inside) / r.total);
        const tone = r.total === 0 ? "none" : r.outside === 0 ? "good" : "bad";
        return (
          <li key={r.key} className={tone}>
            <div className="limit-text">
              <span>{r.label}</span>
              <div className="limit-bar" role="img" aria-label={`${inside} of ${r.total} inside`}>
                <i style={{ width: `${percent ?? 0}%` }} />
              </div>
              <small>
                {r.total === 0 ? "None to count" : `${inside} of ${r.total} inside`}
                {r.outside > 0 && r.to && <> · <Link to={r.to}>{r.outside} outside →</Link></>}
                {r.outside > 0 && !r.to && <> · {r.outside} outside</>}
              </small>
            </div>
            <b className="limit-figure">{percent === null ? "–" : `${percent}%`}</b>
          </li>
        );
      })}
    </ul>
  );
}

// --- more of the period, in pictures ---------------------------------------------

/** Colours that mean nothing but "this product". Each product keeps its colour from one period to the next. */
const PRODUCT_COLORS = ["var(--chart-4)", "var(--chart-2)", "var(--chart-1)", "var(--chart-3)", "var(--chart-5)", "var(--chart-6)"];
export const productColor = (id: number) => PRODUCT_COLORS[id % PRODUCT_COLORS.length];

/** What came in, product by product: a pie with its legend, each slice opening the samples it counts. */
export function ProductMix({ rows }: { rows: ProductScore[] }) {
  const slices: DonutSlice[] = rows
    .filter((r) => r.received > 0)
    .sort((a, b) => b.received - a.received)
    .map((r) => ({ label: r.label, value: r.received, color: productColor(r.id), to: r.to_received }));
  return <DonutChart name="Samples received, by product" slices={slices} centerLabel="received" emptyText="Nothing was received in this period." />;
}

/** Passed and failed results for each product, as one bar each: the longer the bar, the more was tested. */
export function ResultsByProduct({ rows }: { rows: ProductScore[] }) {
  const shown = rows.filter((r) => r.results > 0);
  if (shown.length === 0) return <div className="chart-empty">No results were entered in this period.</div>;
  const most = Math.max(...shown.map((r) => r.results));
  return (
    <div>
      <div className="chart-legend">
        <span><i className="chart-swatch" style={{ background: "var(--pass)" }} aria-hidden="true" />Passed</span>
        <span><i className="chart-swatch" style={{ background: "var(--fail)" }} aria-hidden="true" />Failed</span>
      </div>
      <ol className="stackbars">
        {shown.map((r) => (
          <li key={r.id}>
            <Link to={r.to_results} className="stackbar-row"
              aria-label={`${r.label}: ${r.passed} passed, ${r.failed} failed, of ${r.results} results`}>
              <span className="stackbar-label">{r.label}</span>
              <span className="stackbar-track" style={{ width: `${Math.max((r.results / most) * 100, 4)}%` }}>
                <i className="pass" style={{ flexGrow: r.passed }}>{r.passed > 0 && r.passed / most > 0.08 ? r.passed : ""}</i>
                {r.failed > 0 && <i className="fail" style={{ flexGrow: r.failed }}>{r.failed / most > 0.08 ? r.failed : ""}</i>}
              </span>
              <span className="stackbar-value"><b>{r.pass_rate === null ? "–" : `${Math.round(r.pass_rate)}%`}</b> <small>of {r.results}</small></span>
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** How many samples came in each day, week or month of the period, with the figure on every column. */
export function Intake({ flow }: { flow: ReportTimeline }) {
  const columns: Column[] = flow.points.map((p) => ({
    key: p.date, label: dayLabel(p.date, flow.unit), tip: `${flow.unit === "week" ? "Week of " : ""}${dayLabel(p.date, flow.unit)}`,
    parts: [{ name: "Received", value: p.values[0], color: "var(--chart-4)" }],
    extra: [{ value: String(p.values[1]), label: "completed" }],
  }));
  return <Columns columns={columns} name="Samples received" emptyText="Nothing was received in this period." valueLabels thin />;
}
