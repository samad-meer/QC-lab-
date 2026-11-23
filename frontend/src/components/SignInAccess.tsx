import { useState } from "react";
import { Link } from "react-router-dom";
import { apiPatch, apiPost } from "../api";
import { useAuth } from "../auth";
import type { AdminUser } from "../types";
import { useList } from "../useList";
import { fmtDateTime } from "../util";
import Avatar from "./Avatar";
import ListCard from "./list/ListCard";
import { useToast } from "./Toast";

/**
 * Who may sign in. The tick is Deactivate on the Users screen, not a second
 * list, so the two can never disagree. Beside it: whether they are signed in
 * now, and a lockout after wrong passwords, which can be lifted early.
 */
export default function SignInAccess({ online, onChanged }: {
  /** Signed-in people by id, from the sessions board. */
  online?: Map<number, "active" | "idle">;
  /** Something changed that the rest of the screen shows too. */
  onChanged?: () => void;
}) {
  const toast = useToast();
  const { user: me } = useAuth();
  const users = useList<AdminUser>("/api/auth/users/", { pageKey: "signin_page" });
  const [changing, setChanging] = useState<number | null>(null);

  const act = async (u: AdminUser, work: () => Promise<unknown>, title: string, body?: string) => {
    setChanging(u.id);
    try {
      await work();
      toast("ok", title, body);
      await users.reload();
      onChanged?.();
    } catch (err) {
      toast("error", "Could not change the account", err instanceof Error ? err.message : "");
    } finally {
      setChanging(null);
    }
  };

  const setAllowed = (u: AdminUser, allowed: boolean) =>
    act(u, () => apiPatch(`/api/auth/users/${u.id}/`, { is_active: allowed }),
      allowed ? `${u.name} can sign in` : `${u.name} can no longer sign in`,
      allowed ? undefined : "They are signed out at once. Their records and signatures stay.");

  const unlock = (u: AdminUser) =>
    act(u, () => apiPost(`/api/auth/users/${u.id}/unlock/`, {}), `${u.name} can sign in again`,
      "The lockout is lifted and recorded.");

  return (
    <ListCard
      title="Who can sign in"
      hint={<>Only the people allowed here can sign in. Add people on the <Link to="/admin/users">Users</Link> screen.</>}
      list={users}
      failure="Could not load users"
      emptyTitle="No users yet"
    >
      {(rows) => (
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                <th>Name</th><th>Username</th><th>Role</th><th>Now</th><th>Last sign-in</th><th>Sign-in</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => {
                const now = online?.get(u.id);
                return (
                  <tr key={u.id} style={{ opacity: u.can_sign_in ? 1 : 0.55 }}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <Avatar name={u.name} photoUrl={u.photo_url} size={30} />
                        <div className="cell-title">
                          {u.name}
                          {u.id === me?.id && <span className="badge info" style={{ marginLeft: 7 }}>you</span>}
                        </div>
                      </div>
                    </td>
                    <td className="mono">{u.username}</td>
                    <td>{u.role ? u.role.name : <span className="badge fail">No role</span>}</td>
                    <td>
                      {u.locked_until ? (
                        <div className="si-lock">
                          <span className="badge fail">Locked out</span>
                          <span className="cell-sub">until {fmtDateTime(u.locked_until)}</span>
                          <button className="link-btn" disabled={changing !== null} onClick={() => void unlock(u)}>
                            Unlock
                          </button>
                        </div>
                      ) : now ? (
                        <span className={`si-presence ${now}`}>{now === "active" ? "Online" : "Idle"}</span>
                      ) : (
                        <span className="cell-sub">Not signed in</span>
                      )}
                    </td>
                    <td>{u.last_login ? fmtDateTime(u.last_login) : "never"}</td>
                    <td>
                      <label
                        className="cl-flag"
                        title={u.id === me?.id ? "You cannot block your own account." : undefined}
                      >
                        <input
                          type="checkbox"
                          checked={u.can_sign_in}
                          disabled={u.id === me?.id || changing !== null}
                          onChange={(e) => void setAllowed(u, e.target.checked)}
                        />
                        {u.can_sign_in ? "Allowed" : "Blocked"}
                      </label>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </ListCard>
  );
}
