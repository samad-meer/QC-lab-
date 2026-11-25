import { useAuth } from "../auth";
import Avatar from "./Avatar";

/**
 * Who holds a piece of work, as a chip with their initials. Your own work is
 * picked out, so it is found at a glance in a column or a list of others'.
 */
export default function PersonChip({ id, name, role = "Assigned to" }: {
  id?: number | null;
  name: string;
  /** What the person is to the work, read out on hover. */
  role?: string;
}) {
  const { user } = useAuth();
  if (!name) return <span className="person-chip none">Not assigned</span>;
  const mine = id != null && user?.id === id;
  return (
    <span className={`person-chip${mine ? " mine" : ""}`} title={`${role}: ${name}${mine ? " (you)" : ""}`}>
      <Avatar name={name} size={20} />
      <span>{name}</span>
      {mine && <b>you</b>}
    </span>
  );
}
