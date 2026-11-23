import { useEffect } from "react";
import { SAVE_FAILED } from "../api";
import type { SaveFailed } from "../api";

/**
 * When the server refuses a save, outline the fields it names, on whatever screen is open:
 * those its field errors are keyed by (matched to an input's name or id, or to the label
 * that reads the same, "received_from" → "Received from"), and those its message quotes,
 * as in “Line clearance intimated” already reads 01:53 PM. The first is brought into view
 * and focused. The outline goes when that field is changed, or at the next refusal.
 *
 * No screen has to opt in; one that shows its own field errors still does.
 */
const FLAG = "data-flagged";
const CONTROL = "input:not([type=hidden]), select, textarea, [role=group], [role=radiogroup]";

/** Label text compared loosely: case, spacing, a required star, "(optional)" and a colon ignored. */
function norm(text: string): string {
  return text.toLowerCase().replace(/\(optional\)|\*|:/g, " ").replace(/\s+/g, " ").trim();
}

/** Where to look: an open dialog if there is one, otherwise the page. */
function scope(): ParentNode {
  const dialogs = document.querySelectorAll<HTMLElement>('[role="dialog"]');
  return dialogs.length ? dialogs[dialogs.length - 1] : (document.querySelector("main") ?? document);
}

function visible(el: Element): boolean {
  return (el as HTMLElement).offsetParent !== null || el.getClientRects().length > 0;
}

/** Controls whose label (or aria-label) reads `text`. */
function byLabel(root: ParentNode, text: string): HTMLElement[] {
  const want = norm(text);
  if (!want) return [];
  const found: HTMLElement[] = [];
  root.querySelectorAll<HTMLElement>("[aria-label]").forEach((el) => {
    if (el.matches(CONTROL) && norm(el.getAttribute("aria-label") ?? "") === want) found.push(el);
  });
  root.querySelectorAll<HTMLLabelElement>("label").forEach((label) => {
    // A label's own words are its first line: the control and any note come after.
    const own = norm((label.innerText || label.textContent || "").split("\n")[0]);
    if (own !== want) return;
    const control = label.htmlFor ? document.getElementById(label.htmlFor) : label.querySelector<HTMLElement>(CONTROL);
    if (control) found.push(control);
  });
  return found;
}

/** Controls a field error is keyed by: its name or id, or a label reading the same words. */
function byKey(root: ParentNode, key: string): HTMLElement[] {
  if (key === "detail" || key === "non_field_errors") return [];
  const named = [...root.querySelectorAll<HTMLElement>(`[name="${CSS.escape(key)}"], [id="${CSS.escape(key)}"]`)];
  return named.length ? named : byLabel(root, key.replace(/_id$/, "").replace(/_/g, " "));
}

/** Unflag one control; aria-invalid goes too when it was set here ("own"), not by its screen. */
function unflag(el: Element): void {
  if (el.getAttribute(FLAG) === "own") el.removeAttribute("aria-invalid");
  el.removeAttribute(FLAG);
}

function clearAll(): void {
  document.querySelectorAll(`[${FLAG}]`).forEach(unflag);
}

export function flagFields(message: string, fields: Record<string, string> = {}): void {
  clearAll();
  const root = scope();
  const quoted = [...message.matchAll(/“([^”]{1,120})”|"([^"]{1,120})"/g)].map((m) => m[1] ?? m[2]);
  const targets = [
    ...Object.keys(fields).flatMap((k) => byKey(root, k)),
    ...quoted.flatMap((q) => byLabel(root, q)),
  ].filter((el, i, all) => all.indexOf(el) === i && visible(el));
  targets.forEach((el) => {
    const own = !el.hasAttribute("aria-invalid");
    el.setAttribute(FLAG, own ? "own" : "");
    if (own) el.setAttribute("aria-invalid", "true");
  });
  const first = targets[0];
  if (first) {
    first.scrollIntoView({ block: "center", behavior: "smooth" });
    (first.matches("[role=group], [role=radiogroup]") ? first.querySelector<HTMLElement>("button, input") : first)
      ?.focus({ preventScroll: true });
  }
}

export default function FieldFlags() {
  useEffect(() => {
    const onFail = (e: Event) => {
      const { message, fields } = (e as CustomEvent<SaveFailed>).detail;
      // After the screen has drawn its own error, so a field it shows only then can be found.
      window.setTimeout(() => flagFields(message, fields), 60);
    };
    // Changing a flagged field takes its outline away.
    const onEdit = (e: Event) => {
      const el = (e.target as HTMLElement | null)?.closest(`[${FLAG}]`);
      if (el) unflag(el);
    };
    // A choice made with buttons (Yes / No, a mode) counts as a change too.
    const onClick = (e: Event) => {
      if ((e.target as HTMLElement | null)?.closest(`[role=group][${FLAG}] button`)) onEdit(e);
    };
    window.addEventListener(SAVE_FAILED, onFail);
    document.addEventListener("input", onEdit, true);
    document.addEventListener("change", onEdit, true);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener(SAVE_FAILED, onFail);
      document.removeEventListener("input", onEdit, true);
      document.removeEventListener("change", onEdit, true);
      document.removeEventListener("click", onClick, true);
    };
  }, []);
  return null;
}
