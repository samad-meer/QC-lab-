/**
 * Minimal fetch wrapper: same-origin session auth + Django CSRF.
 */

function getCookie(name: string): string {
  const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return m ? decodeURIComponent(m[1]) : "";
}

let csrfReady = false;

async function ensureCsrf(): Promise<void> {
  if (!csrfReady || !getCookie("csrftoken")) {
    await fetch("/api/auth/csrf/", { credentials: "same-origin" });
    csrfReady = true;
  }
}

/**
 * Field-level errors, keyed by field name, exactly as DRF returns them.
 * Lets a form show "That is not a valid date" beside the date box rather
 * than as one long string at the bottom.
 */
export type FieldErrors = Record<string, string>;

export class ApiError extends Error {
  status: number;
  /** Per-field messages; empty when the failure was not about a field. */
  fields: FieldErrors;

  constructor(status: number, message: string, fields: FieldErrors = {}) {
    super(message);
    this.status = status;
    this.fields = fields;
  }

  /** True when we have something specific to say beside each input. */
  get hasFieldErrors() {
    return Object.keys(this.fields).length > 0;
  }
}

const FRIENDLY: Record<number, string> = {
  0: "Cannot reach the server. Check your connection and try again.",
  403: "You do not have permission to do that.",
  404: "That record no longer exists — it may have been changed by someone else.",
  409: "Someone else changed this first. Reload and try again.",
  500: "Something went wrong on the server. Nothing was saved.",
  502: "The server is not responding. Nothing was saved.",
  503: "The server is busy. Nothing was saved — try again in a moment.",
};

function flatten(value: unknown): string {
  if (Array.isArray(value)) return value.map(flatten).join(" ");
  if (value && typeof value === "object") {
    return Object.values(value as Record<string, unknown>).map(flatten).join(" ");
  }
  return String(value);
}

/** Split a DRF error body into a headline message and per-field messages. */
export function parseErrorBody(status: number, body: unknown): ApiError {
  if (!body || typeof body !== "object") {
    return new ApiError(status, FRIENDLY[status] ?? `Request failed (${status}).`);
  }
  const record = body as Record<string, unknown>;

  if (typeof record.detail === "string") {
    return new ApiError(status, record.detail);
  }

  const fields: FieldErrors = {};
  const general: string[] = [];
  for (const [key, value] of Object.entries(record)) {
    const text = flatten(value).trim();
    if (!text) continue;
    // DRF puts cross-field errors under non_field_errors.
    if (key === "non_field_errors" || key === "__all__") general.push(text);
    else fields[key] = text;
  }

  const count = Object.keys(fields).length;
  const headline =
    general.length > 0
      ? general.join(" ")
      : count === 1
        ? Object.values(fields)[0]
        : count > 1
          ? `${count} fields need attention.`
          : (FRIENDLY[status] ?? `Request failed (${status}).`);

  return new ApiError(status, headline, fields);
}

/** Fired when the server rejects us as unauthenticated, so the app can return to login. */
export const SESSION_LOST = "qclab:session-lost";
/** Fired when the server says the password must change before anything else. */
export const PASSWORD_DUE = "qclab:password-due";
/**
 * Fired when the server refuses a save (any POST, PUT, PATCH, DELETE or upload), so every
 * screen shows it the same way: a toast with the server's words, and the fields it names
 * outlined (Toast.tsx, FieldFlags.tsx). A screen's own handling of the error still runs.
 */
export const SAVE_FAILED = "qclab:save-failed";
export interface SaveFailed {
  message: string;
  fields: FieldErrors;
}

// Signing in and out speak for themselves on their own screen.
const OWN_ERRORS = ["/api/auth/login/", "/api/auth/logout/"];

function announce(url: string, err: unknown): void {
  if (!(err instanceof ApiError) || OWN_ERRORS.some((u) => url.startsWith(u))) return;
  // Signed out, or a new password due: the app takes the person there instead.
  if (err.status === 401 || /credentials were not provided|not logged in|choose a new password/i.test(err.message)) return;
  window.dispatchEvent(new CustomEvent<SaveFailed>(SAVE_FAILED, { detail: { message: err.message, fields: err.fields } }));
}

async function handle<T>(res: Response): Promise<T> {
  if (res.status === 401 || res.status === 403) {
    const body = await res.json().catch(() => ({}));
    const detail: string = body.detail ?? "Not permitted.";
    // A 403 that says "not permitted for your role" is a legitimate answer;
    // one that says we are not authenticated means the session is gone.
    if (res.status === 401 || /credentials were not provided|not logged in/i.test(detail)) {
      window.dispatchEvent(new CustomEvent(SESSION_LOST, { detail: res.status === 401 ? detail : "" }));
    }
    if (body.code === "password_change_required") window.dispatchEvent(new CustomEvent(PASSWORD_DUE));
    throw new ApiError(res.status, detail);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw parseErrorBody(res.status, body);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Turns a network failure into the same shape as a server error. */
async function request<T>(url: string, init: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError(0, FRIENDLY[0]);
  }
  return handle<T>(res);
}

export async function apiGet<T>(url: string): Promise<T> {
  return request<T>(url, { credentials: "same-origin" });
}

/** A request the screen makes by itself. The server does not count it as someone being at the keyboard. */
export async function apiPoll<T>(url: string): Promise<T> {
  return request<T>(url, { credentials: "same-origin", headers: { "X-Background": "1" } });
}

async function send<T>(method: string, url: string, data?: unknown): Promise<T> {
  await ensureCsrf();
  try {
    return await request<T>(url, {
      method,
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCookie("csrftoken"),
      },
      body: data === undefined ? undefined : JSON.stringify(data),
    });
  } catch (err) {
    announce(url, err);
    throw err;
  }
}

export const apiPost = <T,>(url: string, data?: unknown) => send<T>("POST", url, data);
export const apiPut = <T,>(url: string, data?: unknown) => send<T>("PUT", url, data);
export const apiPatch = <T,>(url: string, data?: unknown) => send<T>("PATCH", url, data);
export const apiDelete = <T,>(url: string) => send<T>("DELETE", url);

/** Saves a file the server produces. A refusal arrives as an error, like any other request. */
export async function apiDownload(url: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(url, { credentials: "same-origin" });
  } catch {
    throw new ApiError(0, FRIENDLY[0]);
  }
  if (!res.ok) await handle(res);
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? "report";
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await res.blob());
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

/** Multipart upload (files). The browser sets the boundary header itself. */
export async function apiUpload<T>(url: string, form: FormData): Promise<T> {
  await ensureCsrf();
  try {
    return await request<T>(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": getCookie("csrftoken") },
      body: form,
    });
  } catch (err) {
    announce(url, err);
    throw err;
  }
}
