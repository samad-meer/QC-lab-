import { Link } from "react-router-dom";
import type { InsightDelta, InsightTile } from "../types";
import LineIcon from "./LineIcon";
import type { IconName } from "./LineIcon";

/**
 * The headline figures, each with how it moved against the period before and a small trend of its own.
 * A figure opens the records behind it. A change is never shown by colour alone: it is signed, has an
 * arrow, and is said aloud to a screen reader.
 */

const WIDTH = 120;
const HEIGHT = 36;
const PAD = 4;

/** A line of values over the period, one value to a day, week or month. A gap in the data is a gap in the line. */
export function Sparkline({ values, tone, zero = false, className = "kpi-spark" }: {
  values: (number | null)[];
  tone: string;
  zero?: boolean;
  className?: string;
}) {
  const known = values.filter((v): v is number => v !== null);
  if (known.length < 2) return <svg className={className} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} aria-hidden="true" />;
  // Counts start from nothing, so a quiet week looks quiet; a rate or an average is drawn between its own extremes.
  const low = zero ? Math.min(0, ...known) : Math.min(...known);
  const high = Math.max(...known);
  const span = high - low || 1;
  const x = (i: number) => PAD + (i / (values.length - 1)) * (WIDTH - PAD * 2);
  const y = (v: number) => HEIGHT - PAD - ((v - low) / span) * (HEIGHT - PAD * 2);

  // Runs of consecutive known values; a gap ends one and starts the next.
  const runs: { i: number; v: number }[][] = [];
  values.forEach((v, i) => {
    if (v === null) { runs.push([]); return; }
    if (!runs.length) runs.push([]);
    runs[runs.length - 1].push({ i, v });
  });
  const drawn = runs.filter((r) => r.length > 0);
  const lastIndex = values.reduce<number>((at, v, i) => (v === null ? at : i), -1);

  return (
    <svg className={className} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" aria-hidden="true">
      {drawn.map((run, n) => run.length > 1 && (
        <polygon key={`a${n}`} points={[
          `${x(run[0].i)},${HEIGHT - PAD}`, ...run.map((p) => `${x(p.i)},${y(p.v)}`), `${x(run[run.length - 1].i)},${HEIGHT - PAD}`,
        ].join(" ")} fill={tone} opacity="0.1" />
      ))}
      {drawn.map((run, n) => (
        <polyline key={n} fill="none" stroke={tone} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
          vectorEffect="non-scaling-stroke" points={run.map((p) => `${x(p.i)},${y(p.v)}`).join(" ")} />
      ))}
      {lastIndex >= 0 && (
        <circle cx={x(lastIndex)} cy={y(values[lastIndex] as number)} r="3.5" fill={tone} stroke="var(--surface)" strokeWidth="2"
          vectorEffect="non-scaling-stroke" />
      )}
    </svg>
  );
}

const UNIT: Record<string, string> = { pass_rate: " pts", on_time: " pts", turnaround: "d" };

function signed(n: number) {
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n)}`;
}

/** "+3 (+50%)", "−0.4d", "+2.1 pts": the change, then the share it is of what it was. */
function wording(key: string, d: InsightDelta): string {
  const base = `${signed(d.change)}${UNIT[key] ?? ""}`;
  return d.percent === null ? base : `${base} (${signed(d.percent)}%)`;
}

function Change({ tile, compare }: { tile: InsightTile; compare: string }) {
  const d = tile.delta;
  if (!d) return null;
  if (d.change === 0) return <span className="kpi-delta flat">No change<span className="sr-only"> compared with {compare}</span></span>;
  const up = d.change > 0;
  const better = d.good === null ? null : (d.good === "up") === up;
  const tone = better === null ? "flat" : better ? "good" : "bad";
  return (
    <span className={`kpi-delta ${tone}`}>
      <svg viewBox="0 0 10 10" width="9" height="9" aria-hidden="true"><path d={up ? "M5 1 9 8H1z" : "M5 9 1 2h8z"} fill="currentColor" /></svg>
      {wording(tile.key, d)}
      <span className="sr-only"> compared with {compare}{better === null ? "" : better ? ", better" : ", worse"}</span>
    </span>
  );
}

/** How each headline figure is dressed: volumes are blue, how well and how fast are orange, what is late is red. */
const LOOK: Record<string, { tone: string; icon: IconName }> = {
  received: { tone: "blue", icon: "inbox" },
  completed: { tone: "blue", icon: "box" },
  pass_rate: { tone: "orange", icon: "flask" },
  turnaround: { tone: "orange", icon: "clock" },
  on_time: { tone: "orange", icon: "check" },
  overdue: { tone: "red", icon: "alert" },
};

export default function KpiStrip({ tiles, compare }: { tiles: InsightTile[]; compare: string | null }) {
  return (
    <div className="kpi-strip">
      {tiles.map((t) => {
        const look = LOOK[t.key] ?? { tone: "blue", icon: "chart" as IconName };
        const tone = t.alert ? "var(--fail)" : look.tone === "orange" ? "var(--chart-2)" : "var(--chart-4)";
        return (
          <Link key={t.key} to={t.to} className={`kpi ${look.tone}${t.alert ? " alert" : ""}`}>
            <span className="kpi-icon"><LineIcon name={look.icon} size={20} /></span>
            <span className="kpi-label">{t.label}</span>
            <b className="kpi-value">{t.display}</b>
            {t.delta && compare ? <Change tile={t} compare={compare} /> : <span className="kpi-delta flat">{t.sub && !t.spark ? t.sub : " "}</span>}
            {t.spark && <Sparkline values={t.spark} tone={tone} zero={t.key === "received" || t.key === "completed"} />}
            {t.spark && <span className="kpi-sub">{t.sub}</span>}
          </Link>
        );
      })}
    </div>
  );
}
