import { Message } from "../Feedback";

/**
 * Shown to an administrator at a step that is not theirs — before they act,
 * so that stepping in is a decision and never an accident.
 */
export default function OverrideNotice({ rules }: { rules: string[] }) {
  if (rules.length === 0) return null;
  return (
    <div style={{ marginBottom: 16 }}>
      <Message kind="warn">
        <b>You are stepping in as administrator.</b> Normally: {rules.join(" ")} You can go ahead,
        in your own name — everything you do here is flagged as an override in the activity log.
      </Message>
    </div>
  );
}
