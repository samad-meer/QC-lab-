import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { apiPoll } from "../api";
import { LAB_REGISTER_VIEWS, useAuth } from "../auth";
import { useTheme } from "../theme";
import type { Summary, Tasks } from "../types";
import AdminMenu from "./AdminMenu";
import type { AdminLink } from "./AdminMenu";
import AccountMenu from "./AccountMenu";
import Avatar from "./Avatar";
import BrandMark from "./BrandMark";
import { Backdrop } from "./Decor";
import { NotificationBell, POLL_MS, useNotifications } from "./Notifications";

/**
 * How far the top bar has had to give way to keep its menu on one line. Each step
 * gives up a little more, and the steps add up: 1 tighter spacing; 2 your name and
 * role hide behind your picture and Sign out keeps only its icon; 3 the tagline
 * hides and a long lab name is shortened; 4 smaller menu text. The lab's name never
 * goes: it is who the bar belongs to.
 * When even that is not enough, the menu takes a row of its own.
 * Measured, not guessed from the width: what the bar holds depends on the role, the
 * lab's name and the zoom.
 */
const FIT_STEPS = 4;
/** Under this width the bar is one compact row and the menu opens from a button (see .topbar in index.css). */
const COMPACT = 960;

function fitBar(bar: HTMLElement, menu: HTMLElement) {
  const wraps = () => {
    const items = Array.from(menu.children) as HTMLElement[];
    return items.length > 1 && items.some((el) => el.offsetTop > items[0].offsetTop + 4);
  };
  let step = 0;
  bar.dataset.fit = "";
  // A phone or a small window has its own layout: one row, and the menu opens from a button.
  if (window.innerWidth <= COMPACT) return;
  while (step < FIT_STEPS && wraps()) {
    step += 1;
    bar.dataset.fit = Array.from({ length: step }, (_, i) => i + 1).join(" ");
  }
  // Still too narrow (a small window, or a very large zoom): two tidy rows, the
  // menu on a row of its own, rather than a menu broken across lines.
  if (wraps()) bar.dataset.fit = "rows";
}

const SETTINGS_ICON = (
  <svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true">
    <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" strokeWidth="2" />
    <path
      d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"
      fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"
    />
  </svg>
);

export default function Layout({ children }: { children: ReactNode }) {
  const { user, titles, can, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const location = useLocation();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [tasks, setTasks] = useState(0);
  const bell = useNotifications().data;
  const newest = bell ? (bell.items[0]?.id ?? 0) : null; // null until the bell has first been read
  const [menuOpen, setMenuOpen] = useState(false);
  const toggleButton = useRef<HTMLButtonElement>(null);

  // Refresh the nav badges whenever the route changes — after signing or
  // sending work back, the count the user sees should already be right — and
  // whenever a notification arrives, every 30 seconds, and on returning to
  // the window, so work that lands on you shows without changing page.
  const refreshBadges = useCallback(() => {
    apiPoll<Summary>("/api/summary/").then(setSummary).catch(() => setSummary(null));
    apiPoll<Tasks>("/api/tasks/").then((t) => setTasks(t.actionable)).catch(() => setTasks(0));
  }, []);

  useEffect(() => {
    refreshBadges();
  }, [refreshBadges, location.pathname]);

  // A notification arriving means work may have landed on you. The first time the bell is read is
  // not an arrival: this page has just refreshed the badges itself, so doing it again would only
  // repeat the two slowest calls of every page load.
  const lastSeen = useRef<number | null>(null);
  useEffect(() => {
    if (newest === null) return;
    if (lastSeen.current !== null && newest > lastSeen.current) refreshBadges();
    lastSeen.current = newest;
  }, [newest, refreshBadges]);

  useEffect(() => {
    const timer = window.setInterval(refreshBadges, POLL_MS);
    window.addEventListener("focus", refreshBadges);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refreshBadges);
    };
  }, [refreshBadges]);

  // The compact menu closes when a page opens, on Escape, on a click or tap outside the bar, and
  // when the window grows wide enough for the full menu. Opened, it takes the keyboard's place (its
  // links come before the bar's buttons in the page); closed with Escape, focus goes back to its button.
  useEffect(() => setMenuOpen(false), [location.pathname]);
  useEffect(() => {
    if (!menuOpen) return undefined;
    menu.current?.querySelector<HTMLElement>("a, button")?.focus({ preventScroll: true });
    const outside = (e: Event) => {
      if (!bar.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenuOpen(false);
        toggleButton.current?.focus();
      }
    };
    const resize = () => {
      if (window.innerWidth > COMPACT) setMenuOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    window.addEventListener("resize", resize);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key);
      window.removeEventListener("resize", resize);
    };
  }, [menuOpen]);

  // The tab says which page this is, then the system's name as set in Settings.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const heading = document.querySelector("main h1")?.textContent;
      document.title = heading ? `${heading} · ${titles.lab_name}` : titles.lab_name;
    }, 400);
    return () => window.clearTimeout(timer);
  }, [titles.lab_name, location.pathname]);

  // Keep the menu on one line, whatever the window, the zoom and the role: measured
  // again whenever the bar or its menu changes size, and once the fonts have loaded.
  const bar = useRef<HTMLElement>(null);
  const menu = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const header = bar.current;
    const nav = menu.current;
    if (!header || !nav) return undefined;
    const fit = () => fitBar(header, nav);
    fit();
    const watch = new ResizeObserver(fit);
    watch.observe(header);
    watch.observe(nav);
    void document.fonts?.ready.then(fit);
    return () => watch.disconnect();
  }, [user, tasks, summary, titles.lab_name, titles.app_tagline, location.pathname]);

  if (!user) return null;
  const waiting = summary?.awaiting_me ?? 0;

  // Administration lives in one menu, so the bar fits however many of
  // these pages a role may open. Each page is "setup" (configuring the lab)
  // or "quality" (overseeing the work); the menu is named and headed from that.
  const adminLinks: AdminLink[] = [
    can("user.manage") && { group: "setup", to: "/admin/users", label: "Users", hint: "Accounts, roles and sections",
      icon: "M16 19c0-2.8-1.8-5-4-5s-4 2.2-4 5M12 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6M20 18c0-2-1-3.6-2.5-4.4M17 5.2a3 3 0 0 1 0 5.6" },
    can("user.manage") && { group: "setup", to: "/admin/sign-in", label: "Sign-in and sessions",
      hint: "Who is online, who may sign in",
      icon: "M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3" },
    can("role.manage") && { group: "setup", to: "/admin/roles", label: "Roles", hint: "What each role may do",
      icon: "M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6zM9 12l2 2 4-4" },
    can("config.manage") && { group: "setup", to: "/admin/sections", label: "Sections", hint: "The lab's sections and their codes",
      icon: "M4 5h7v6H4zM13 5h7v6h-7zM4 13h7v6H4zM13 13h7v6h-7z" },
    can("config.manage") && { group: "setup", to: "/admin/received-from", label: "Received from", hint: "Who samples arrive from",
      icon: "M3 7h11v9H3zM14 10h4l3 3v3h-7M7 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4M17 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4" },
    // Specifications are reached through their product, so whoever drafts or approves them needs it too.
    (can("product.manage") || can("spec.manage") || can("spec.approve")) && { group: "setup", to: "/admin/products", label: "Products", hint: "Products, their specifications and QC stages",
      icon: "M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9" },
    can("product.manage") && { group: "setup", to: "/admin/checkpoint-kinds", label: "Check point kinds", hint: "Values a batch record can ask for",
      icon: "M3 17 17 3l4 4L7 21zM7 13l2 2M10 10l2 2M13 7l2 2" },
    can("template.manage") && { group: "setup", to: "/admin/certificate-templates", label: "Certificate templates", hint: "Title, footer, optional details",
      icon: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6" },
    can("notification.manage") && { group: "setup", to: "/admin/notification-rules", label: "Notification rules", hint: "Which alerts go out, and to whom",
      icon: "M6 16V11a6 6 0 1 1 12 0v5l2 2H4zM10 21h4" },
    can("investigation.approve") && { group: "quality", to: "/admin/quality-rules", label: "Quality rules", hint: "What must happen after a failure",
      icon: "M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6zM12 8v5M12 16h.01" },
    can("workflow.manage") && { group: "setup", to: "/admin/workflows", label: "Workflows", hint: "Review stages per product",
      icon: "M5 6h4v4H5zM15 14h4v4h-4zM9 8h3a2 2 0 0 1 2 2v4a2 2 0 0 0 2 2" },
    can("audit.view") && { group: "quality", to: "/admin/analytics", label: "Analytics", hint: "Throughput, quality, workload",
      icon: "M4 20V10M10 20V4M16 20v-7M22 20H2" },
    can("audit.view") && { group: "quality", to: "/admin/audit", label: "Activity log", hint: "Who did what, and when",
      icon: "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" },
  ].filter((l): l is AdminLink => Boolean(l));

  return (
    <>
    <Backdrop />
    <div className="app-shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className={`topbar${menuOpen ? " menu-open" : ""}`} ref={bar}>
        <Link to="/dashboard" className="brand" title={`${titles.lab_name} — open the dashboard`}>
          <BrandMark />
          <div className="brand-text">
            <b>{titles.lab_name}</b>
            {titles.app_tagline && <span>{titles.app_tagline}</span>}
          </div>
        </Link>

        <nav className="topnav" id="main-menu" aria-label="Main" ref={menu}>
          <NavLink to="/tasks">
            My tasks
            {tasks > 0 && <span className="nav-count">{tasks}</span>}
          </NavLink>
          {can("sample.register") && <NavLink to="/frontdesk">Receive samples</NavLink>}
          {can("sample.assign") && <NavLink to="/assign">Assign work</NavLink>}
          {/* An administrator works from All samples; this is theirs only once something is assigned to them. */}
          {can("result.enter") && (!can("admin.override") || waiting > 0) && (
            <NavLink to="/worklist">
              My worklist
              {waiting > 0 && <span className="nav-count">{waiting}</span>}
            </NavLink>
          )}
          {user.is_reviewer && (
            <NavLink to="/queue">
              Awaiting my signature
              {waiting > 0 && <span className="nav-count">{waiting}</span>}
            </NavLink>
          )}
          {can("sample.view.all") && <NavLink to="/samples" end>All samples</NavLink>}
          {(can("sample.view.all") || can("batch.view.all")) && <NavLink to="/batches">Batches</NavLink>}
          {LAB_REGISTER_VIEWS.some(can) && <NavLink to="/lab">Lab records</NavLink>}
          {can("report.view") && <NavLink to="/reports">Reports</NavLink>}
          {adminLinks.length > 0 && <AdminMenu links={adminLinks} />}
          {/* On a small screen these leave the bar and wait in the menu, with their names. */}
          <div className="nav-tools">
            {can("config.manage") && <NavLink to="/admin/settings" className="nav-tool">{SETTINGS_ICON}Settings</NavLink>}
            <button type="button" className="nav-tool" onClick={toggle}>
              <span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
              {theme === "dark" ? "Light theme" : "Dark theme"}
            </button>
            <Link to="/profile" className="nav-tool">My account</Link>
            <button type="button" className="nav-tool nav-signout" onClick={() => void logout()}>Sign out</button>
          </div>
        </nav>

        <div className="topbar-right">
          <NotificationBell />
          {/* On a computer, you are one menu: account, settings, theme, Sign out. */}
          <AccountMenu
            name={user.name}
            role={user.designation || user.role?.name || "No role"}
            photoUrl={user.photo_url}
            theme={theme}
            onTheme={toggle}
            onSignOut={() => void logout()}
            settingsIcon={can("config.manage") ? SETTINGS_ICON : undefined}
          />
          {/* On a phone the picture opens My account, and the rest waits in the menu. */}
          <Link to="/profile" className="identity compact-only" title="My account">
            <Avatar name={user.name} photoUrl={user.photo_url} />
          </Link>
          <button type="button" ref={toggleButton} className="icon-btn menu-toggle" aria-label={menuOpen ? "Close the menu" : "Open the menu"}
            aria-expanded={menuOpen} aria-controls="main-menu" onClick={() => setMenuOpen((o) => !o)}>
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path d={menuOpen ? "M6 6l12 12M18 6L6 18" : "M4 7h16M4 12h16M4 17h16"} fill="none" stroke="currentColor"
                strokeWidth="2.2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </header>
      <main className="page" id="main" tabIndex={-1}>{children}</main>
    </div>
    </>
  );
}
