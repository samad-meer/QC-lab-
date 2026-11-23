import type { CertContentTest, TestDefinition } from "../types";

/** A point on the gauge's arc: f=0 is the left end, f=1 the right. */
function point(f: number) {
  const angle = Math.PI + Math.max(0, Math.min(1, f)) * Math.PI;
  return { x: 60 + 46 * Math.cos(angle), y: 60 + 46 * Math.sin(angle) };
}

function arc(from: number, to: number) {
  const a = point(from);
  const b = point(to);
  return `M${a.x.toFixed(2)} ${a.y.toFixed(2)} A46 46 0 0 1 ${b.x.toFixed(2)} ${b.y.toFixed(2)}`;
}

/**
 * Where the allowed band and the result sit on a shared axis, as 0–1
 * fractions — or null when the test has no numeric limit to draw.
 */
function scale(def: TestDefinition | undefined, value: number) {
  if (!def || Number.isNaN(value)) return null;
  const min = def.min_value === null ? null : Number(def.min_value);
  const max = def.max_value === null ? null : Number(def.max_value);
  let lo: number, hi: number, bandLo: number, bandHi: number;
  if (def.limit_type === "NUMERIC_RANGE" && min !== null && max !== null) {
    const pad = (max - min) * 0.25 || Math.abs(max) * 0.1 || 1;
    [lo, hi, bandLo, bandHi] = [min - pad, max + pad, min, max];
  } else if (def.limit_type === "NUMERIC_MAX" && max !== null) {
    [lo, hi, bandLo, bandHi] = [0, Math.max(max * 1.5, value * 1.1), 0, max];
  } else if (def.limit_type === "NUMERIC_MIN" && min !== null) {
    const top = Math.max(min * 1.3, value * 1.05);
    [lo, hi, bandLo, bandHi] = [min * 0.8, top, min, top];
  } else {
    return null;
  }
  const f = (v: number) => (v - lo) / (hi - lo);
  return { band: [f(bandLo), f(bandHi)] as const, value: f(value) };
}

/**
 * Each result as a gauge card: the arc is the allowed range, the dot is
 * the result — how close a value sits to its limit is visible at a glance.
 * Text and report-only results get a plain card.
 */
export default function ResultGauges({ tests, definitions }: { tests: CertContentTest[]; definitions: TestDefinition[] }) {
  const byName = new Map(definitions.map((d) => [d.name, d]));
  return (
    <div className="gauges">
      {tests.map((t) => {
        const g = scale(byName.get(t.name), Number(t.value));
        const cls = t.outcome === "FAIL" ? "fail" : t.outcome === "REPORTED" ? "reported" : "";
        const dot = g ? point(g.value) : null;
        return (
          <div key={t.name} className={`gauge-card ${cls}`}>
            <div className="gauge-head">
              <b>{t.name}</b>
              {t.outcome === "REPORTED" ? (
                <span className="badge muted">Reported</span>
              ) : (
                <span className="gauge-tick" aria-label={t.outcome === "PASS" ? "Pass" : "Fail"}>
                  {t.outcome === "PASS" ? "✓" : "✕"}
                </span>
              )}
            </div>
            {g && dot ? (
              <>
                <svg className="gauge-svg" viewBox="0 0 120 70" aria-hidden="true">
                  <path className="gauge-arc-track" d={arc(0, 1)} fill="none" style={{ strokeWidth: 9, strokeLinecap: "round" }} />
                  <path className="gauge-arc-band" d={arc(g.band[0], g.band[1])} fill="none" style={{ strokeWidth: 9, strokeLinecap: "round" }} />
                  <circle className="gauge-dot" cx={dot.x} cy={dot.y} r="7" style={{ strokeWidth: 3 }} />
                </svg>
                <div className="gauge-value">
                  {t.value}
                  {t.unit && <small> {t.unit}</small>}
                </div>
              </>
            ) : (
              <div className="gauge-word">
                {t.value}
                {t.unit && <small style={{ fontSize: 12, color: "var(--ink-3)" }}> {t.unit}</small>}
              </div>
            )}
            <div className="gauge-limit">{t.limit_text}</div>
          </div>
        );
      })}
    </div>
  );
}
