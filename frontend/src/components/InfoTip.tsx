import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { MouseEvent, ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * A small "i" beside a label that opens a short explanation: what the field is
 * for, and what to do when its list is empty. Opened by a click, a tap or the
 * keyboard, and closed by Escape or a click elsewhere. The note is drawn on the
 * page itself, so a scrolling table or a card never cuts it off.
 */
export default function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();

  // Below the icon, or above it when there is no room; never off the side of the screen.
  useLayoutEffect(() => {
    if (!open || !button.current || !panel.current) return;
    const b = button.current.getBoundingClientRect();
    const p = panel.current.getBoundingClientRect();
    const left = Math.max(16, Math.min(b.left - 14, window.innerWidth - p.width - 16));
    const below = b.bottom + 8;
    const top = below + p.height > window.innerHeight - 8 ? Math.max(8, b.top - 8 - p.height) : below;
    setPos({ top, left });
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const close = () => {
      setOpen(false);
      setPos(null);
    };
    const outside = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!panel.current?.contains(target) && !button.current?.contains(target)) close();
    };
    // Escape closes the note only. Caught before anything else sees it, so a dialog the
    // note sits in stays open with what was typed in it.
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      close();
      button.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key, true);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [open]);

  const toggle = (e: MouseEvent) => {
    // Inside a <label> or a <summary>, the click would otherwise focus the field or fold the section.
    e.preventDefault();
    e.stopPropagation();
    setOpen((was) => !was);
    setPos(null);
  };

  return (
    <>
      <button
        ref={button}
        type="button"
        className="info-tip"
        aria-label={`About ${label}`}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={toggle}
      >
        <svg viewBox="0 0 24 24" width="11" height="11" aria-hidden="true">
          <path d="M12 10.5v7M12 6.5h.01" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
      </button>
      {open && createPortal(
        <div
          ref={panel}
          id={id}
          role="note"
          className="info-tip-panel"
          style={pos ?? { top: 0, left: 0, visibility: "hidden" }}
        >
          <b>{label}</b>
          {children}
        </div>,
        document.body,
      )}
    </>
  );
}
