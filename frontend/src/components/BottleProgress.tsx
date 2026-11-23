import type { JourneyStep } from "./Stepper";

// Pills resting in the bottle, bottom up. Decorative.
const PILLS: { left?: number; right?: number; bottom: number; rotate: number; a: string; b: string }[] = [
  { left: 14, bottom: 14, rotate: -20, a: "#2dd4bf", b: "#fde68a" },
  { right: 12, bottom: 26, rotate: 25, a: "#c4b5fd", b: "#ffffff" },
  { left: 40, bottom: 50, rotate: -8, a: "#fb923c", b: "#ffffff" },
  { left: 12, bottom: 82, rotate: 14, a: "#818cf8", b: "#fde68a" },
];

/**
 * The journey as a medicine bottle filling with pills, beside a
 * checklist that lights up the step waiting on someone — glowing when
 * that someone is you.
 */
export default function BottleProgress({ steps, mine = false }: { steps: JourneyStep[]; mine?: boolean }) {
  const total = steps.length;
  const done = steps.filter((s) => s.state === "done").length;
  const currentIndex = steps.findIndex((s) => s.state === "current");
  const stepNo = currentIndex >= 0 ? currentIndex + 1 : total;
  const fill = Math.round((done / total) * 100);
  const pillsShown = Math.min(PILLS.length, Math.ceil((done / total) * PILLS.length));

  return (
    <div className="bottle-row">
      <div className="bottle" aria-hidden="true">
        <div className="bottle-cap" />
        <div className="bottle-body">
          <div className="bottle-fill" style={{ height: `${fill}%` }}>
            {fill > 0 && fill < 100 && <span className="bottle-wave" />}
          </div>
          {PILLS.slice(0, pillsShown).map((p, i) => (
            <span
              key={i}
              className="bottle-pill"
              style={{
                left: p.left, right: p.right, bottom: p.bottom,
                transform: `rotate(${p.rotate}deg)`,
                background: `linear-gradient(90deg, ${p.a} 50%, ${p.b} 50%)`,
              }}
            />
          ))}
          <div className="bottle-label">
            <b>{stepNo}/{total}</b>
            <span>{done === total ? "complete" : "current step"}</span>
          </div>
        </div>
      </div>

      <ol className="checklist" aria-label={`Step ${stepNo} of ${total}`}>
        {steps.map((s, i) => (
          <li key={s.key} className={`${s.state} ${s.state === "current" && mine ? "mine" : ""}`}>
            <span className="check-dot" aria-hidden="true">{s.state === "done" ? "✓" : i + 1}</span>
            <span>
              <b>{s.label}</b>{" "}
              <span className="who-text">· {s.state === "current" && mine ? "you" : s.who}</span>
              {s.state === "done" && <span className="sr-only"> (done)</span>}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
