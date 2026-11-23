import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// /api and /verify are proxied to Django so the SPA is same-origin with the
// backend in development — session-cookie auth, no CORS.
// Override with BACKEND_PORT if you run Django somewhere else.
const BACKEND = `http://127.0.0.1:${process.env.BACKEND_PORT ?? 8007}`;

export default defineConfig(({ mode }) => {
  // DEV_LAN=1 (in frontend/.env.local) lets other computers on this network open
  // the screens at http://<this computer's IP>:5173. Off unless asked for: the
  // sign-in page lists the demo logins. Django stays on 127.0.0.1 either way;
  // only these screens are reachable, and they pass /api on to it.
  // Vite restarts itself when .env.local changes, so the switch takes effect at once.
  const lan = loadEnv(mode, process.cwd(), "").DEV_LAN === "1";
  return {
    plugins: [react()],
    server: {
      host: lan ? true : undefined,
      proxy: {
        "/api": BACKEND,
        "/verify": BACKEND,
        "/site-admin": BACKEND,
        "/static": BACKEND,
      },
    },
  };
});
