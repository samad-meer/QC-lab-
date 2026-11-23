import { Capsule3D, Molecule, Ring } from "./Decor";

export interface HeroFact {
  label: string;
  value: string;
  hot?: boolean;
}

/**
 * The top of a sample, review or certificate screen: the product large,
 * where it stands, and — when it is waiting for you — a live "your turn".
 */
export default function SampleHero({
  productName,
  sampleNo,
  batchNo,
  batchCaption = "Batch",
  specVersion,
  workflow,
  pill,
  facts,
  step,
}: {
  productName: string;
  sampleNo: string;
  batchNo: string;
  /** "Reference" for a sample that is not from a batch. */
  batchCaption?: string;
  specVersion: number;
  workflow: string;
  pill: { tone: "hot" | "done" | "plain"; text: string };
  /** Up to two floating facts beside the molecule. */
  facts: HeroFact[];
  /** Current step number, total steps, and how many are complete. */
  step: { current: number; total: number; done: number; label: string };
}) {
  // "Ibuprofen (API)" → "Ibuprofen" large, "(API)" in the subtitle.
  const match = productName.match(/^(.*?)\s*(\(.*\))?$/);
  const name = match?.[1] || productName;
  const qualifier = match?.[2] ?? "";
  // Long product names ("Paracetamol 500 mg Tablets") step down in size
  // so the longest word always fits beside the molecule.
  const titleSize = name.length <= 10 ? 76 : name.length <= 16 ? 62 : name.length <= 24 ? 52 : 44;

  return (
    <section className="hero" aria-label="Sample">
      <div className="hero-main">
        <Capsule3D width={118} />
        <div className="hero-text">
          <span className={`hero-pill ${pill.tone}`}>
            <span className="live" aria-hidden="true" />
            {pill.text}
          </span>
          <h1
            className="hero-title"
            style={{ fontSize: `clamp(32px, 6vw, ${titleSize}px)`, letterSpacing: titleSize > 60 ? -3 : -1.5 }}
          >
            {name}
          </h1>
          <div className="hero-sub">
            {qualifier && <>{qualifier} · </>}specification v{specVersion}
          </div>
          <div className="hero-chips">
            <span className="hero-chip"><span className="k">Sample</span><span className="v">{sampleNo}</span></span>
            <span className="hero-chip"><span className="k">{batchCaption}</span><span className="v">{batchNo}</span></span>
            <span className="hero-chip"><span className="k">Workflow</span><span className="v">{workflow}</span></span>
          </div>
        </div>
      </div>

      <div className="hero-art">
        <Molecule />
        {facts[0] && (
          <div className={`float-chip ${facts[0].hot ? "hot" : ""}`} style={{ left: 0, top: 6 }}>
            <span className="k">{facts[0].label}</span>
            <b>{facts[0].value}</b>
          </div>
        )}
        {facts[1] && (
          <div className={`float-chip ${facts[1].hot ? "hot" : ""}`} style={{ right: 4, top: 26, animationDelay: "-2s" }}>
            <span className="k">{facts[1].label}</span>
            <b>{facts[1].value}</b>
          </div>
        )}
        <div className="float-chip ring-chip" style={{ right: 24, bottom: 8, animationDelay: "-3.5s" }}>
          <Ring step={step.current} total={step.total} done={step.done} />
          <span>
            <span className="k">Step</span>
            <b style={{ fontFamily: "var(--font)" }}>{step.label}</b>
          </span>
        </div>
      </div>
    </section>
  );
}
