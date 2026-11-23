import { useEffect } from "react";
import { useBlocker } from "react-router-dom";
import ConfirmModal from "./ConfirmModal";

/**
 * Put on a screen that holds unsaved edits: it asks before the app moves
 * away, and the browser asks before a reload or a closed tab.
 */
export default function UnsavedChangesGuard({ dirty }: { dirty: boolean }) {
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname,
  );

  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (blocker.state !== "blocked") return null;
  return (
    <ConfirmModal
      title="Leave without saving?"
      confirmText="Leave without saving"
      cancelText="Stay here"
      onConfirm={() => blocker.proceed()}
      onClose={() => blocker.reset()}
    >
      Your changes on this page have not been saved.
    </ConfirmModal>
  );
}
