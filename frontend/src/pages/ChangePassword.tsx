import { useAuth } from "../auth";
import PasswordForm from "../components/PasswordForm";

/** Stands in front of the whole app while a password is temporary or has expired. */
export default function ChangePassword() {
  const { user, logout } = useAuth();
  return (
    <main style={{ display: "grid", placeItems: "center", minHeight: "100vh", padding: 16 }}>
      <section className="card" style={{ width: "100%", maxWidth: 460, margin: 0 }}>
        <div className="card-head"><h1 style={{ fontSize: 20, margin: 0 }}>Choose a new password</h1></div>
        <div className="card-body stack">
          <p className="hint" style={{ margin: 0 }}>
            {user?.name}, your password was set by an administrator or has expired. Your password is your
            signature, so only you should know it.
          </p>
          <PasswordForm />
          <button className="subtle" onClick={() => void logout()}>Sign out</button>
        </div>
      </section>
    </main>
  );
}
