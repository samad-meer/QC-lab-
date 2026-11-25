import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import Avatar from "./Avatar";

/**
 * You: your picture, and under it what is yours to do — your account, the lab's settings (for
 * whoever sets them), the theme, and Sign out. One button where there were four, so the top bar
 * keeps its room for the menu and the lab's name. A disclosure like the Admin menu: Tab moves
 * through it, Escape closes it and returns to the picture.
 */
export default function AccountMenu({ name, role, photoUrl, theme, onTheme, onSignOut, settingsIcon }: {
  name: string;
  /** Their designation, else their role. */
  role: string;
  photoUrl?: string | null;
  theme: "light" | "dark";
  onTheme: () => void;
  onSignOut: () => void;
  /** Set only for someone who may change the lab's settings. */
  settingsIcon?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const panelId = useId();
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  // Close on navigation, on a click outside, and on Escape.
  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        button.current?.focus();
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
    <div className="account-menu" ref={wrap}>
      <button ref={button} type="button" className="account-btn" aria-expanded={open} aria-controls={panelId}
        title="Your account" onClick={() => setOpen((o) => !o)}>
        <Avatar name={name} photoUrl={photoUrl} />
        <span className="who">
          <b>{name}</b>
          <span>{role}</span>
        </span>
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" className="chev">
          <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="account-panel" id={panelId}>
          <div className="account-head">
            <Avatar name={name} photoUrl={photoUrl} size={42} />
            <span>
              <b>{name}</b>
              <small>{role}</small>
            </span>
          </div>
          <Link to="/profile" className="account-item">
            <span className="ico" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="18" height="18">
                <path d="M16 19c0-2.8-1.8-5-4-5s-4 2.2-4 5M12 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6" fill="none" stroke="currentColor"
                  strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span><b>My account</b><small>Photo, password and what you can do</small></span>
          </Link>
          {settingsIcon && (
            <Link to="/admin/settings" className="account-item">
              <span className="ico" aria-hidden="true">{settingsIcon}</span>
              <span><b>Settings</b><small>The lab's name, features and rules</small></span>
            </Link>
          )}
          <button type="button" className="account-item" onClick={() => { onTheme(); setOpen(false); }}>
            <span className="ico" aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
            <span><b>{theme === "dark" ? "Light theme" : "Dark theme"}</b><small>Easier on the eyes {theme === "dark" ? "by day" : "at night"}</small></span>
          </button>
          <div className="account-sep" />
          <button type="button" className="account-item signout-item" onClick={onSignOut}>
            <span className="ico" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="18" height="18">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" fill="none" stroke="currentColor"
                  strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span><b>Sign out</b><small>Leave this computer safely</small></span>
          </button>
        </div>
      )}
    </div>
  );
}
