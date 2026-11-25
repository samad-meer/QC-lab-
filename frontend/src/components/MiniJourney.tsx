import type { SampleListItem } from "../types";

/**
 * A sample's place on its journey, small enough for a row or a card: one dot for each step
 * (received, tested, each review, printed), filled as they are done. The step it is at is
 * ringed, and picked out when it is waiting for the person looking.
 */
export default function MiniJourney({ s }: { s: Pick<SampleListItem, "journey" | "status" | "my_turn" | "status_label"> }) {
  const j = s.journey;
  if (!j || j.total === 0) return null;
  const finished = s.status === "APPROVED";
  const hasName = s.status_label ? ` — ${s.status_label}` : "";
  return (
    <span
      className="mini-journey"
      role="img"
      aria-label={finished ? `All ${j.total} steps done` : `${j.done} of ${j.total} steps done${hasName}`}
      title={finished ? `All ${j.total} steps done` : `${j.done} of ${j.total} steps done${hasName}`}
    >
      {Array.from({ length: j.total }, (_, i) => {
        const state = i < j.done ? "done" : i === j.done && !finished ? (s.my_turn ? "mine" : "now") : "next";
        return <i key={i} className={state} />;
      })}
    </span>
  );
}
