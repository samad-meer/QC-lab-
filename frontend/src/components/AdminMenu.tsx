import { useEffect, useId, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

/**
 * "setup": how the lab is configured (people, products, workflows…).
 * "quality": oversight of the work itself (quality rules, activity log, analytics).
 */
export type AdminGroup = "setup" | "quality";

export interface AdminLink {
  to: string;
  label: string;
  hint: string;
  icon: string; // SVG path data, 24×24, stroked
  group: AdminGroup;
}

const GROUP_TITLES: Record<AdminGroup, string> = { setup: "Setup", quality: "Quality oversight" };

/**
 * The administration pages, folded into one menu so the top bar never
 * overflows. A disclosure (button + list of links), not an ARIA menu:
 * it is navigation, and Tab moves through it like any other links.
 *
 * The menu is named for what it holds: "Admin" when it has any setup page,
 * "Quality" when it holds oversight pages alone (a QA officer's), so no one
 * is shown an Admin menu they cannot administer anything from. Holding both,
 * it heads each group.
 */
export default function AdminMenu({ links }: { links: AdminLink[] }) {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const panelId = useId();
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const current = links.find((l) => location.pathname.startsWith(l.to));
  // A link without a known group counts as setup, so it is never dropped from the menu.
  const groupOf = (l: AdminLink): AdminGroup => (l.group === "quality" ? "quality" : "setup");
  const groups = (["setup", "quality"] as const)
    .map((g) => ({ key: g, links: links.filter((l) => groupOf(l) === g) }))
    .filter((g) => g.links.length > 0);
  const title = groups.some((g) => g.key === "setup") ? "Admin" : "Quality";
  const headed = groups.length > 1;

  // Close on navigation, on a click outside, and on Escape.
  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="nav-menu" ref={wrapRef}>
      <button
        ref={buttonRef}
        type="button"
        className={`nav-menu-button ${current ? "active" : ""}`}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
      >
        {title}{current && <span className="nav-menu-current"> · {current.label}</span>}
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" className="chev">
          <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className={`nav-menu-panel ${links.length > 4 ? "two-col" : ""}`} id={panelId}>
          {groups.map((g) => [
            headed && <div key={`h-${g.key}`} className="nav-menu-heading">{GROUP_TITLES[g.key]}</div>,
            ...g.links.map((l) => (
              <NavLink key={l.to} to={l.to}>
                <span className="ico" aria-hidden="true">
                  <svg viewBox="0 0 24 24" width="18" height="18">
                    <path d={l.icon} fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
                <span>
                  <b>{l.label}</b>
                  <small>{l.hint}</small>
                </span>
              </NavLink>
            )),
          ])}
        </div>
      )}
    </div>
  );
}
