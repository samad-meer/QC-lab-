import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { apiPoll, apiPost } from "../api";
import type { NotificationItem, NotificationsResponse } from "../types";
import { EmptyState } from "./Feedback";
import Stamp from "./Stamp";
import { useToast } from "./Toast";

export const POLL_MS = 30_000;

interface Api {
  data: NotificationsResponse | null;
  refresh: () => Promise<void>;
  open: (n: NotificationItem) => Promise<void>;
  markAll: () => Promise<void>;
}

const Ctx = createContext<Api>({
  data: null,
  refresh: async () => {},
  open: async () => {},
  markAll: async () => {},
});

export const useNotifications = () => useContext(Ctx);

/**
 * Keeps the signed-in person's notifications fresh: on every page change,
 * every 30 seconds, and when the window regains focus. Anything new since
 * the last look pops up as a toast.
 */
export function NotificationsProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState<NotificationsResponse | null>(null);
  const newest = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const d = await apiPoll<NotificationsResponse>("/api/notifications/");
      const top = d.items[0]?.id ?? 0;
      if (newest.current === null) {
        // First look after signing in: say what is waiting, once.
        if (d.unread > 0) {
          toast("info", `You have ${d.unread} unread notification${d.unread === 1 ? "" : "s"}`,
            d.items.find((n) => !n.read_at)?.title);
        }
      } else if (top > newest.current) {
        const fresh = d.items.filter((n) => n.id > (newest.current ?? 0) && !n.read_at);
        if (fresh.length === 1) toast("info", fresh[0].title, fresh[0].body || undefined);
        else if (fresh.length > 1) toast("info", `${fresh.length} new notifications`, fresh[0].title);
      }
      newest.current = Math.max(newest.current ?? 0, top);
      setData(d);
    } catch {
      /* the bell keeps what it had; the next poll tries again */
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
  }, [refresh, location.pathname]);

  useEffect(() => {
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  const open = useCallback(async (n: NotificationItem) => {
    if (!n.read_at) {
      try {
        setData(await apiPost<NotificationsResponse>(`/api/notifications/${n.id}/read/`));
      } catch {
        /* still take them there */
      }
    }
    if (n.link) navigate(n.link);
  }, [navigate]);

  const markAll = useCallback(async () => {
    setData(await apiPost<NotificationsResponse>("/api/notifications/read-all/"));
  }, []);

  return <Ctx.Provider value={{ data, refresh, open, markAll }}>{children}</Ctx.Provider>;
}

// kind -> [tone, icon path]
const KIND: Record<string, [string, string]> = {
  ASSIGNED: ["hot", "M12 3v12 M7 10l5 5 5-5 M4 19h16"],
  HANDOVER: ["hot", "M4 12h12 M12 6l6 6-6 6 M20 4v16"],
  YOUR_TURN: ["hot", "M5 12l5 5L20 7"],
  REASSIGNED: ["muted", "M4 7h13l-3-3 M20 17H7l3 3"],
  HANDOVER_ACCEPTED: ["pass", "M5 12l5 5L20 7"],
  HANDOVER_DECLINED: ["fail", "M6 6l12 12 M18 6L6 18"],
  HANDOVER_CANCELLED: ["muted", "M6 6l12 12 M18 6L6 18"],
  RETURNED: ["fail", "M9 14L4 9l5-5 M4 9h11a5 5 0 0 1 0 10h-3"],
  ON_HOLD: ["warn", "M9 5v14 M15 5v14"],
  RELEASED: ["pass", "M7 5l12 7-12 7z"],
  RETEST_REQUESTED: ["info", "M9 3h6 M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"],
  RETEST_AUTHORIZED: ["pass", "M9 3h6 M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"],
  RETEST_DECLINED: ["fail", "M9 3h6 M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"],
  CERT_RELEASED: ["pass", "M7 3h7l5 5v13H7z M14 3v5h5 M10 15l2 2 4-4"],
  CALIBRATION_DUE: ["warn", "M12 7v5l3 2 M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18"],
  CALIBRATION_OVERDUE: ["fail", "M12 7v5l3 2 M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18"],
  QUALIFICATION_DUE: ["warn", "M12 7v5l3 2 M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18"],
  QUALIFICATION_EXPIRED: ["fail", "M12 7v5l3 2 M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18"],
};

/** The list itself — used in the bell's panel and on the dashboard. */
export function NotificationList({ items, limit }: { items: NotificationItem[]; limit?: number }) {
  const { open } = useNotifications();
  const shown = limit ? items.slice(0, limit) : items;
  if (shown.length === 0) {
    return <EmptyState icon="🔔" title="No notifications yet" sub="When work is assigned or handed to you, you will hear about it here." />;
  }
  return (
    <ul className="notif-list">
      {shown.map((n) => {
        const [tone, icon] = KIND[n.kind] ?? ["info", "M12 8v5 M12 16h.01"];
        return (
          <li key={n.id}>
            <button type="button" className={`notif-item ${n.read_at ? "" : "unread"}`} onClick={() => void open(n)}>
              <span className={`notif-ico ${tone}`} aria-hidden="true">
                <svg viewBox="0 0 24 24" width="16" height="16">
                  <path d={icon} fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
              <span className="notif-text">
                <b>{n.title}</b>
                {n.body && <span className="notif-body">{n.body}</span>}
                <Stamp at={n.created_at} by={n.actor} />
              </span>
              {!n.read_at && <span className="notif-dot" aria-label="Unread" />}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/** The bell in the top bar: unread count, and the latest notifications on click. */
export function NotificationBell() {
  const { data, markAll } = useNotifications();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const panelId = useId();
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const unread = data?.unread ?? 0;

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
    <div className="notif-wrap" ref={wrapRef}>
      <button
        ref={buttonRef}
        type="button"
        className={`icon-btn notif-bell ${unread > 0 ? "has-unread" : ""}`}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
        title="Notifications"
        onClick={() => setOpen((o) => !o)}
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z M10 20a2 2 0 0 0 4 0" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {unread > 0 && <span className="notif-count">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="notif-panel" id={panelId}>
          <div className="notif-head">
            <b>Notifications</b>
            {unread > 0 && <span className="badge hot">{unread} unread</span>}
            <div className="spacer" />
            {unread > 0 && (
              <button type="button" className="link-btn" onClick={() => void markAll()}>Mark all read</button>
            )}
          </div>
          <div className="notif-scroll">
            <NotificationList items={data?.items ?? []} limit={12} />
          </div>
          <Link to="/dashboard" className="notif-foot">Open the dashboard →</Link>
        </div>
      )}
    </div>
  );
}
