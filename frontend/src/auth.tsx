import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { apiGet, apiPost, PASSWORD_DUE, SESSION_LOST } from "./api";
import type { DemoLogin, LabConfig, LabTitles, Permission, User } from "./types";
import { setLabClock, setLabZone } from "./util";

interface AuthState {
  user: User | null;
  titles: LabTitles;
  demoLogins: DemoLogin[];
  demoPassword: string;
  loading: boolean;
  /** Why the person was signed out, for the sign-in screen to say. */
  notice: string;
  /** Nothing in the UI asks "which role is this?" — it asks what you may do. */
  can: (permission: Permission) => boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  /** Re-read /me/ after the user changes their own profile. */
  refreshUser: () => Promise<void>;
  /** Re-read the system name and tagline after an administrator changes them. */
  refreshConfig: () => Promise<void>;
}

const DEFAULT_TITLES: LabTitles = {
  lab_name: "Quality Control Laboratory",
  app_tagline: "Certificate of Analysis",
};

const AuthContext = createContext<AuthState>({
  user: null,
  titles: DEFAULT_TITLES,
  demoLogins: [],
  demoPassword: "",
  loading: true,
  notice: "",
  can: () => false,
  login: async () => {
    throw new Error("not ready");
  },
  logout: async () => {},
  refreshUser: async () => {},
  refreshConfig: async () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [titles, setTitles] = useState<LabTitles>(DEFAULT_TITLES);
  const [demoLogins, setDemoLogins] = useState<DemoLogin[]>([]);
  const [demoPassword, setDemoPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");

  const loadConfig = useCallback(async () => {
    try {
      const cfg = await apiGet<LabConfig>("/api/auth/config/");
      setTitles(cfg);
      setLabZone(cfg.time_zone);
      setLabClock(cfg.time_format);
      setDemoLogins(cfg.demo_logins ?? []);
      setDemoPassword(cfg.demo_password ?? "");
    } catch {
      /* keep defaults — the login screen still works */
    }
  }, []);

  useEffect(() => {
    (async () => {
      // Config is public, so the login screen gets the lab's name and any
      // demo shortcuts before anyone signs in.
      await loadConfig();
      try {
        setUser(await apiGet<User>("/api/auth/me/"));
      } catch {
        /* not logged in */
      } finally {
        setLoading(false);
      }
    })();
  }, [loadConfig]);

  // If any request comes back unauthenticated, drop straight to the login
  // screen rather than leaving the user on a dead page.
  useEffect(() => {
    const onLost = (e: Event) => {
      setUser(null);
      setNotice((e as CustomEvent<string>).detail ?? "");
    };
    const onPasswordDue = () => setUser((u) => (u ? { ...u, must_change_password: true } : u));
    window.addEventListener(SESSION_LOST, onLost);
    window.addEventListener(PASSWORD_DUE, onPasswordDue);
    return () => {
      window.removeEventListener(SESSION_LOST, onLost);
      window.removeEventListener(PASSWORD_DUE, onPasswordDue);
    };
  }, []);

  const login = async (username: string, password: string) => {
    const u = await apiPost<User>("/api/auth/login/", { username, password });
    setNotice("");
    setUser(u);
    await loadConfig();
    return u;
  };

  const logout = async () => {
    // Clear locally whatever the server says — if the session already
    // expired the POST 403s, and the user must still get back to login.
    try {
      await apiPost("/api/auth/logout/");
    } finally {
      setUser(null);
    }
  };

  const can = useCallback(
    (permission: Permission) => !!user?.permissions?.includes(permission),
    [user],
  );

  const refreshUser = useCallback(async () => {
    try {
      setUser(await apiGet<User>("/api/auth/me/"));
    } catch {
      /* a failed refresh must not sign anyone out */
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user, titles, demoLogins, demoPassword, loading, notice, can, login, logout, refreshUser,
        refreshConfig: loadConfig,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

/** Seeing each Lab records register. A role that sees none has no Lab records in its menu. */
export const LAB_REGISTER_VIEWS: Permission[] = [
  "instrument.view", "material.view", "method.view", "qualification.view", "retained.view", "change.view",
];

/**
 * Where everyone lands: after signing in, after a first password is chosen, and when an address
 * is "/" or unknown or a page their role may not open. The dashboard, for every role: it shows
 * what is waiting on that person, whatever they are, and links on to the rest. A role the lab
 * invents needs no code change here.
 */
export const HOME_PATH = "/dashboard";
