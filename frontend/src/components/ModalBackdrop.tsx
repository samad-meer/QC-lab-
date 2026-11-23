import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE = "a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled])";

/**
 * The dimmed layer behind a dialog. It is placed on <body>, not where it is
 * used: a card's backdrop-filter traps position: fixed inside that card, which
 * would leave the dialog dimming only the card and sliding under the top bar.
 *
 * A click outside does nothing: these dialogs hold typed reasons and passwords,
 * and a stray click must not lose them. Escape closes; Tab stays inside; focus
 * goes back where it was afterwards.
 */
export default function ModalBackdrop({ onClick, children }: { onClick?: () => void; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClick);
  close.current = onClick;

  useEffect(() => {
    const dialog = box.current;
    if (!dialog) return undefined;
    const before = document.activeElement as HTMLElement | null;
    const heading = dialog.querySelector("h1,h2,h3");
    if (heading?.textContent) dialog.setAttribute("aria-label", heading.textContent);
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (!dialog.contains(document.activeElement)) focusable()[0]?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close.current?.();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusable();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    dialog.addEventListener("keydown", onKey);
    return () => {
      dialog.removeEventListener("keydown", onKey);
      before?.focus?.();
    };
  }, []);

  return createPortal(
    <div
      ref={box}
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      onClick={(e) => e.stopPropagation()} // React bubbles through a portal: a row behind must not see it
    >
      {children}
    </div>,
    document.body,
  );
}
