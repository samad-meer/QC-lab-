import { useId } from "react";

/**
 * Decorative pieces of the theme. All are aria-hidden: they carry no
 * information that is not also written out as text beside them.
 */

/** Slow-drifting colour clouds behind the whole app. */
export function Backdrop() {
  return (
    <div className="backdrop" aria-hidden="true">
      <span className="c1" />
      <span className="c2" />
      <span className="c3" />
      <span className="c4" />
    </div>
  );
}

/** A glossy two-tone capsule that floats. */
export function Capsule3D({ width = 130 }: { width?: number }) {
  return (
    <div className="capsule3d" style={{ ["--cap-w" as string]: `${width}px` }} aria-hidden="true">
      <span className="shine" />
      <span className="seam" />
    </div>
  );
}

// A ball-and-stick ring molecule (an aryl-propionic skeleton). Coordinates
// in a 520×360 box; colours come from the theme's --atom-* tokens.
const BONDS =
  "M308 180L284 221.6 M284 221.6L236 221.6 M236 221.6L212 180 M212 180L236 138.4 M236 138.4L284 138.4 " +
  "M284 138.4L308 180 M308 180L356 180 M356 180L378 226 M356 180L404 150 M404 150L452 164 M404 150L398 100 " +
  "M398 100L428 76 M212 180L164 160 M164 160L120 186 M120 186L76 160 M120 186L118 236";
const SIDE_BONDS =
  " M284 221.6L297 244 M236 221.6L223 244 M236 138.4L223 116 M284 138.4L297 116 M378 226L366 262 " +
  "M378 226L408 240 M76 160L48 178 M76 160L64 124 M118 236L92 258 M118 236L140 264 M278.7 212.4L241.3 212.4 " +
  "M222.6 180L241.3 147.6 M278.7 147.6L297.4 180 M402 156.7L450 170.7";
const CARBONS: [number, number][] = [
  [308, 180], [284, 221.6], [236, 221.6], [212, 180], [236, 138.4], [284, 138.4], [356, 180],
  [378, 226], [404, 150], [164, 160], [120, 186], [76, 160], [118, 236],
];
const OXYGENS: [number, number][] = [[452, 164], [398, 100]];
const HYDROGENS: [number, number][] = [
  [297, 244], [223, 244], [223, 116], [297, 116], [428, 76], [366, 262], [408, 240],
  [48, 178], [64, 124], [92, 258], [140, 264],
];

function Atom({ id, stops }: { id: string; stops: [string, string, string] }) {
  return (
    <radialGradient id={id} cx="35%" cy="30%" r="70%">
      <stop offset="0" style={{ stopColor: stops[0] }} />
      <stop offset="0.45" style={{ stopColor: stops[1] }} />
      <stop offset="1" style={{ stopColor: stops[2] }} />
    </radialGradient>
  );
}

/** A floating 3D molecule — decoration for hero panels. */
export function Molecule({ className = "molecule" }: { className?: string }) {
  const uid = useId().replace(/:/g, "");
  const c = `c${uid}`, o = `o${uid}`, h = `h${uid}`, halo = `halo${uid}`;
  return (
    <svg className={className} viewBox="0 0 520 360" aria-hidden="true" preserveAspectRatio="xMidYMid meet">
      <defs>
        <Atom id={c} stops={["var(--atom-c1)", "var(--atom-c2)", "var(--atom-c3)"]} />
        <Atom id={o} stops={["var(--atom-o1)", "var(--atom-o2)", "var(--atom-o3)"]} />
        <Atom id={h} stops={["var(--atom-h1)", "var(--atom-h2)", "var(--atom-h3)"]} />
        <radialGradient id={halo} cx="50%" cy="50%" r="50%">
          <stop offset="0" style={{ stopColor: "var(--molecule-halo)" }} />
          <stop offset="1" style={{ stopColor: "var(--molecule-halo)", stopOpacity: 0 }} />
        </radialGradient>
      </defs>
      <ellipse cx="260" cy="190" rx="250" ry="165" fill={`url(#${halo})`} />
      <g className="float-group">
        <path d={BONDS + SIDE_BONDS} fill="none" style={{ stroke: "var(--bond)", strokeWidth: 8, strokeLinecap: "round" }} />
        <path d={BONDS} fill="none" style={{ stroke: "var(--bond-hi)", strokeWidth: 2.2, strokeLinecap: "round", strokeOpacity: 0.8 }} />
        <g fill={`url(#${h})`}>{HYDROGENS.map(([x, y]) => <circle key={`${x}-${y}`} cx={x} cy={y} r="10" />)}</g>
        <g fill={`url(#${c})`}>{CARBONS.map(([x, y]) => <circle key={`${x}-${y}`} cx={x} cy={y} r="18" />)}</g>
        <g fill={`url(#${o})`}>{OXYGENS.map(([x, y]) => <circle key={`${x}-${y}`} cx={x} cy={y} r="19" />)}</g>
      </g>
    </svg>
  );
}

/** A small progress ring: current step of total. */
export function Ring({ step, total, done }: { step: number; total: number; done: number }) {
  const uid = useId().replace(/:/g, "");
  const r = 24;
  const circ = 2 * Math.PI * r;
  const filled = Math.max(0, Math.min(1, done / total)) * circ;
  return (
    <svg className="ring" viewBox="0 0 60 60" width="56" height="56" role="img" aria-label={`Step ${step} of ${total}`}>
      <defs>
        <linearGradient id={`rg${uid}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" style={{ stopColor: "#2dd4bf" }} />
          <stop offset="1" style={{ stopColor: "#8b5cf6" }} />
        </linearGradient>
      </defs>
      <circle cx="30" cy="30" r={r} fill="none" style={{ stroke: "var(--track)", strokeWidth: 6 }} />
      <circle
        cx="30" cy="30" r={r} fill="none" transform="rotate(-90 30 30)"
        style={{ stroke: `url(#rg${uid})`, strokeWidth: 6, strokeLinecap: "round", strokeDasharray: `${filled} ${circ}` }}
      />
      <text x="30" y="35" textAnchor="middle" style={{ fill: "var(--ink)", fontSize: 15, fontWeight: 800, fontFamily: "var(--display)" }}>
        {step}/{total}
      </text>
    </svg>
  );
}
