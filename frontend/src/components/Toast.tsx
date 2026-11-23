import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { SAVE_FAILED } from "../api";
import type { SaveFailed } from "../api";
import FieldFlags from "./FieldFlags";

type Kind = "ok" | "error" | "info";

interface Toast {
  id: number;
  kind: Kind;
  title: string;
  detail?: string;
}

interface ToastApi {
  toast: (kind: Kind, title: string, detail?: string) => void;
}

const ToastContext = createContext<ToastApi>({ toast: () => {} });

const ICON: Record<Kind, string> = { ok: "✓", error: "!", info: "i" };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  // An error already shown in the last few seconds is not shown twice: a refused save is
  // toasted for every screen (below), and some screens toast the same words themselves.
  const recent = useRef(new Map<string, number>());
  const toast = useCallback(
    (kind: Kind, title: string, detail?: string) => {
      if (kind === "error") {
        const key = (detail || title).trim();
        const now = Date.now();
        if (now - (recent.current.get(key) ?? 0) < 3000) return;
        recent.current.set(key, now);
      }
      const id = nextId.current++;
      setToasts((list) => [...list, { id, kind, title, detail }]);
      // Errors stay longer — they usually need reading, not just noticing.
      window.setTimeout(() => dismiss(id), kind === "error" ? 8000 : 4500);
    },
    [dismiss],
  );

  // Every save the server refuses, on any screen, in the server's own words.
  useEffect(() => {
    const onFail = (e: Event) => toast("error", "Not saved", (e as CustomEvent<SaveFailed>).detail.message);
    window.addEventListener(SAVE_FAILED, onFail);
    return () => window.removeEventListener(SAVE_FAILED, onFail);
  }, [toast]);

  return (
    <ToastContext.Provider value={{ toast }}>
      <FieldFlags />
      {children}
      <div className="toast-stack" aria-live="polite" aria-atomic="false">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`} role={t.kind === "error" ? "alert" : "status"}>
            <span className="toast-icon" aria-hidden="true">{ICON[t.kind]}</span>
            <div className="toast-body">
              <b>{t.title}</b>
              {t.detail && <span>{t.detail}</span>}
            </div>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss">×</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext).toast;
}
