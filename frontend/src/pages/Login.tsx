import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { homeFor, useAuth } from "../auth";
import BrandMark from "../components/BrandMark";
import { Backdrop, Capsule3D, Molecule } from "../components/Decor";
import { initials } from "../components/SignatureGrid";
import { useTheme } from "../theme";

const JOURNEY = [
  ["Received", "The front desk records what arrived and assigns a trained analyst"],
  ["Tested", "Results entered against the stored limits — pass or fail decided automatically"],
  ["Reviewed", "The product's own review stages, in order — one signature or several"],
  ["Released", "The last signature releases the certificate"],
  ["Printed", "Original once, then numbered duplicates — every copy recorded"],
];

// One colour per journey step, teal through to coral.
const ORB_FILLS = [
  "linear-gradient(135deg, #14b8a6, #0f766e)",
  "linear-gradient(135deg, #22d3ee, #0e7490)",
  "linear-gradient(135deg, #818cf8, #4f46e5)",
  "linear-gradient(135deg, #c084fc, #7c3aed)",
  "linear-gradient(135deg, #fb923c, #c2410c)",
];

// Avatar fills for the demo accounts; white initials pass 4.5:1 on each.
const AVATAR_FILLS = [
  "linear-gradient(135deg, #0f766e, #0e7490)",
  "linear-gradient(135deg, #4f46e5, #6d28d9)",
  "linear-gradient(135deg, #c2410c, #9a3412)",
  "linear-gradient(135deg, #0369a1, #1d4ed8)",
  "linear-gradient(135deg, #be185d, #9d174d)",
  "linear-gradient(135deg, #15803d, #166534)",
  "linear-gradient(135deg, #7c3aed, #6d28d9)",
];

function Icon({ d, size = 16 }: { d: string; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const ICONS = {
  pen: "M4 20l4-1 11-11-3-3L5 16z M14 6l3 3",
  qr: "M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h2v2h-2z M18 14h2 M14 18h2 M18 18h2v2",
  audit: "M8 6h12 M8 12h12 M8 18h12 M4 6h.01 M4 12h.01 M4 18h.01",
  lock: "M6 11h12v9H6z M8 11V8a4 4 0 0 1 8 0v3",
  archive: "M4 7h16v3H4z M5 10v9h14v-9 M10 14h4",
  people: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6 M3 20c0-3 2.7-5 6-5s6 2 6 5 M17 11a3 3 0 1 0 0-6 M21 20c0-2.4-1.5-4.2-4-4.8",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6",
  key: "M15 7a4 4 0 1 1-3.5 6L5 19.5V22H2v-3l6.5-6.5A4 4 0 0 1 15 7z M16 8h.01",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6",
  eyeOff: "M3 3l18 18 M10.6 5.1A10.4 10.4 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.2 M6.6 6.6C3.9 8.4 2 12 2 12s3.6 7 10 7a9.7 9.7 0 0 0 5.4-1.6 M9.9 9.9a3 3 0 0 0 4.2 4.2",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10 M12 1v2 M12 21v2 M4.2 4.2l1.4 1.4 M18.4 18.4l1.4 1.4 M1 12h2 M21 12h2 M4.2 19.8l1.4-1.4 M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
};

function FeatureChip({ icon, children, style }: { icon: string; children: ReactNode; style: React.CSSProperties }) {
  return (
    <span className="feature-chip" style={style}>
      <span className="feature-ico"><Icon d={icon} /></span>
      {children}
    </span>
  );
}

export default function Login() {
  const { login, titles, demoLogins, demoPassword, notice } = useAuth();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = await login(username.trim(), password);
      navigate(homeFor(user), { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
      setBusy(false);
      setPassword("");
      passwordRef.current?.focus();
    }
  };

  // Demo shortcuts only ever appear when the backend is in DEBUG.
  const useDemo = (name: string) => {
    setUsername(name);
    setPassword(demoPassword);
    setError("");
  };

  useEffect(() => {
    document.title = `Sign in — ${titles.lab_name}`;
  }, [titles.lab_name]);

  return (
    <>
    <Backdrop />
    <div className="login-page">
      <aside className="login-aside">
        <div className="login-art" aria-hidden="true">
          <Molecule />
          <div className="art-capsule"><Capsule3D width={118} /></div>
          <FeatureChip icon={ICONS.pen} style={{ left: "1%", top: "4%" }}>Password e-signatures</FeatureChip>
          <FeatureChip icon={ICONS.audit} style={{ left: "24%", bottom: "0%", animationDelay: "-3.5s" }}>Full audit trail</FeatureChip>
          <FeatureChip icon={ICONS.qr} style={{ right: "0%", bottom: "0%", animationDelay: "-2s" }}>QR-verified certificates</FeatureChip>
        </div>

        <div>
          <div className="aside-eyebrow">Quality control{titles.app_tagline ? ` · ${titles.app_tagline}` : ""}</div>
          <h2>From the front desk to a signed certificate</h2>
          <p className="lede">
            The same people, the same order, the same signatures — with nothing left to get
            lost, and every step recorded as it happens.
          </p>
        </div>

        <ol className="orb-journey">
          {JOURNEY.map(([step, detail], i) => (
            <li key={step}>
              <span className="orb" style={{ background: ORB_FILLS[i] }}>{i + 1}</span>
              <span>
                <b>{step}</b>
                <small>{detail}</small>
              </span>
            </li>
          ))}
        </ol>

        <ul className="rule-pills">
          <li><Icon d={ICONS.lock} /> A signature locks the document</li>
          <li><Icon d={ICONS.archive} /> Nothing is ever deleted</li>
          <li><Icon d={ICONS.people} /> Every signature, a named person</li>
        </ul>
      </aside>

      <main className="login-main">
        <button
          type="button"
          className="icon-btn login-theme"
          onClick={toggle}
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          title={theme === "dark" ? "Light theme" : "Dark theme"}
        >
          <Icon d={theme === "dark" ? ICONS.sun : ICONS.moon} size={18} />
        </button>

        <form className="login-form" onSubmit={submit}>
          <div className="login-brand">
            <BrandMark size={54} />
            <div>
              <span className="login-kicker">{titles.lab_name}</span>
              <h1>Welcome back</h1>
            </div>
          </div>
          <p className="tag">Sign in with your laboratory account. Your password is also your signature.</p>

          <label className="field" htmlFor="username">
            Username
            <span className="input-wrap">
              <Icon d={ICONS.user} size={18} />
              <input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                placeholder="e.g. analyst.gf"
                autoFocus
                required
              />
            </span>
          </label>
          <label className="field" htmlFor="password">
            Password
            <span className="input-wrap has-toggle">
              <Icon d={ICONS.key} size={18} />
              <input
                id="password"
                ref={passwordRef}
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                placeholder="Your password"
                required
              />
              <button
                type="button"
                className="pw-toggle"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                aria-pressed={showPassword}
              >
                <Icon d={showPassword ? ICONS.eyeOff : ICONS.eye} size={18} />
              </button>
            </span>
          </label>

          {notice && !error && (
            <div className="msg info" role="status">
              <span className="msg-icon">i</span>
              <span>{notice}</span>
            </div>
          )}
          {error && (
            <div className="msg error" role="alert">
              <span className="msg-icon">!</span>
              <span>{error}</span>
            </div>
          )}

          <button className="primary block big" disabled={busy}>
            {busy ? "Signing in…" : <>Sign in <Icon d={ICONS.arrow} size={18} /></>}
          </button>

          {demoLogins.length > 0 && (
            <div className="demo-panel">
              <div className="demo-head">Demo accounts — development only</div>
              <div className="demo-grid">
                {demoLogins.map((d, i) => (
                  <button
                    type="button"
                    key={d.username}
                    className={`demo-btn ${username === d.username ? "selected" : ""}`}
                    onClick={() => useDemo(d.username)}
                    aria-pressed={username === d.username}
                  >
                    <span className="demo-avatar" style={{ background: AVATAR_FILLS[i % AVATAR_FILLS.length] }} aria-hidden="true">
                      {initials(d.name)}
                    </span>
                    <span style={{ minWidth: 0 }}>
                      <b>{d.role}</b>
                      <span>{d.username}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="login-foot">
            <Icon d={ICONS.lock} size={14} /> Every sign-in and every action is recorded in the audit trail.
          </div>
        </form>
      </main>
    </div>
    </>
  );
}
