import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPoll, apiPost } from "../../api";
import { useAuth } from "../../auth";
import Avatar from "../../components/Avatar";
import ConfirmModal from "../../components/ConfirmModal";
import { Message, TableSkeleton } from "../../components/Feedback";
import SignInAccess from "../../components/SignInAccess";
import { useToast } from "../../components/Toast";
import type { SignInBoard, SignInSession } from "../../types";
import { fmtDateTime } from "../../util";

const REFRESH_MS = 30_000;
// Recent sign-ins shown before "Show all".
const FIRST_RECENT = 10;

function minutesSince(iso: string | null, now: number): number | null {
  return iso ? Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60_000)) : null;
}

function ago(minutes: number | null): string {
  if (minutes === null) return "—";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min ago`;
}

/**
 * Sign-in and sessions: who is signed in right now, on which computer, who may
 * sign in at all, and the sign-ins recorded. Reads again every 30 seconds,
 * quietly, so leaving it open does not count as activity.
 */
export default function SignIns() {
  const toast = useToast();
  const { can } = useAuth();
  const [board, setBoard] = useState<SignInBoard | null>(null);
  const [error, setError] = useState("");
  const [ending, setEnding] = useState<SignInSession | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [allRecent, setAllRecent] = useState(false);

  const load = useCallback(async (quietly = false) => {
    try {
      const url = "/api/auth/sessions/";
      setBoard(quietly ? await apiPoll<SignInBoard>(url) : await apiGet<SignInBoard>(url));
      setNow(Date.now());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load who is signed in.");
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(true), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const online = useMemo(() => {
    const map = new Map<number, "active" | "idle">();
    for (const s of board?.sessions ?? []) {
      if (map.get(s.user.id) !== "active") map.set(s.user.id, s.state);
    }
    return map;
  }, [board]);

  const end = async () => {
    if (!ending) return;
    const r = await apiPost<{ detail: string }>(`/api/auth/sessions/${ending.id}/end/`, {});
    toast("ok", "Signed out", r.detail);
    setEnding(null);
    await load();
  };

  if (!board) {
    return error
      ? <Message kind="error">{error}</Message>
      : <div className="card"><div className="card-body flush"><TableSkeleton /></div></div>;
  }
  const s = board.summary;
  const computers = board.sessions.length;
  const recent = allRecent ? board.recent : board.recent.slice(0, FIRST_RECENT);

  return (
    <>
      <div className="page-head">
        <h1>Sign-in and sessions</h1>
        <p className="sub">
          Who is signed in right now and on which computer, who may sign in at all, and every sign-in recorded.
          Someone idle for {board.idle_minutes} minutes is signed out by themselves. This screen updates every
          30 seconds.
        </p>
      </div>

      {error && <div style={{ marginBottom: 14 }}><Message kind="error">{error}</Message></div>}

      <div className="task-tiles">
        <div className={`task-tile ${s.online ? "info" : "zero"} still`}>
          <b>{s.online}</b><span>Online now</span>
          <small>{s.online === 1 ? "Person" : "People"} active in the last {board.active_minutes} minutes</small>
        </div>
        <div className={`task-tile ${s.signed_in ? "info" : "zero"} still`}>
          <b>{s.signed_in}</b><span>Signed in</span>
          <small>
            {s.signed_in === 1 ? "Person" : "People"}, online or idle, on {computers} computer{computers === 1 ? "" : "s"}
          </small>
        </div>
        <div className={`task-tile ${s.allowed ? "info" : "zero"} still`}>
          <b>{s.allowed}</b><span>Can sign in</span><small>Allowed, with a working role</small>
        </div>
        <div className={`task-tile ${s.blocked ? "info" : "zero"} still`}>
          <b>{s.blocked}</b><span>Blocked</span><small>Their records and signatures stay</small>
        </div>
        <div className={`task-tile ${s.locked ? "fail" : "zero"} still`}>
          <b>{s.locked}</b><span>Locked out</span><small>After five wrong passwords, for 15 minutes</small>
        </div>
      </div>

      <section className="card" aria-label="Signed in now">
        <div className="card-head">
          <h2>Signed in now</h2>
          <span className="hint">One row per computer. Signing someone out here leaves their account as it is.</span>
        </div>
        <div className="card-body flush">
          {board.sessions.length === 0 ? (
            <p className="cell-sub" style={{ padding: "16px 20px", margin: 0 }}>Nobody is signed in right now.</p>
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr><th>Person</th><th>Status</th><th>Signed in</th><th>Last activity</th><th>Computer</th><th /></tr>
                </thead>
                <tbody>
                  {board.sessions.map((row) => {
                    const quiet = minutesSince(row.last_activity, now);
                    const left = row.signs_out_at
                      ? Math.max(0, Math.ceil((new Date(row.signs_out_at).getTime() - now) / 60_000)) : null;
                    return (
                      <tr key={row.id}>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <Avatar name={row.user.name} photoUrl={row.user.photo_url} size={30} />
                            <div>
                              <div className="cell-title">
                                {row.user.name}
                                {row.current && <span className="badge info" style={{ marginLeft: 7 }}>you, here</span>}
                              </div>
                              <div className="cell-sub">{row.user.role || "No role"}</div>
                            </div>
                          </div>
                        </td>
                        <td>
                          <span className={`si-presence ${row.state}`}>
                            {row.state === "active" ? "Online" : `Idle ${quiet ?? ""} min`}
                          </span>
                          {row.state === "idle" && left !== null && (
                            <div className="cell-sub">Signed out in {left} min unless they work</div>
                          )}
                        </td>
                        <td>{row.signed_in_at ? fmtDateTime(row.signed_in_at) : <span className="cell-sub">Before this screen existed</span>}</td>
                        <td>{ago(quiet)}</td>
                        <td>
                          <div>{row.device || "Unknown computer"}</div>
                          {row.ip && <div className="cell-sub mono">{row.ip}</div>}
                        </td>
                        <td style={{ textAlign: "right" }}>
                          {!row.current && (
                            <button className="subtle small" onClick={() => setEnding(row)}>Sign out…</button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      <SignInAccess online={online} onChanged={() => void load()} />

      <section className="card" aria-label="Recent sign-ins">
        <div className="card-head">
          <h2>Recent sign-ins</h2>
          <span className="hint">Newest first, including wrong passwords and lockouts</span>
          <div className="spacer" />
          {can("audit.view") && <Link to="/admin/audit" className="btn-link">Full activity log →</Link>}
        </div>
        <div className="card-body flush">
          {board.recent.length === 0 ? (
            <p className="cell-sub" style={{ padding: "16px 20px", margin: 0 }}>Nothing recorded yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead><tr><th>When</th><th>Person</th><th>What happened</th><th>From</th></tr></thead>
                <tbody>
                  {recent.map((e) => (
                    <tr key={e.id}>
                      <td style={{ whiteSpace: "nowrap" }}>{fmtDateTime(e.at)}</td>
                      <td>{e.person}</td>
                      <td>
                        <span className={`badge ${e.tone}`}>{e.label}</span>
                        {e.by && <span className="cell-sub"> by {e.by}</span>}
                      </td>
                      <td className="mono">{e.ip || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {board.recent.length > FIRST_RECENT && (
            <div className="actions-bar" style={{ padding: "10px 20px 14px", margin: 0 }}>
              <button className="subtle small" onClick={() => setAllRecent((v) => !v)}>
                {allRecent ? `Show the latest ${FIRST_RECENT}` : `Show all ${board.recent.length}`}
              </button>
            </div>
          )}
        </div>
      </section>

      {ending && (
        <ConfirmModal
          title={`Sign ${ending.user.name} out?`}
          confirmText="Sign out"
          onConfirm={end}
          onClose={() => setEnding(null)}
        >
          <p style={{ marginTop: 0 }}>
            {ending.user.name} is signed out on <b>{ending.device || "that computer"}</b>
            {ending.ip ? <> ({ending.ip})</> : null} at once, and anything they have not saved there is lost.
          </p>
          <p className="cell-sub" style={{ marginBottom: 0 }}>
            Their account stays as it is: they can sign in again. To stop them signing in, block them under Who
            can sign in. This is recorded in the activity log.
          </p>
        </ConfirmModal>
      )}
    </>
  );
}
