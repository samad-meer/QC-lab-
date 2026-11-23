import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiPut } from "../../api";
import { Message, TableSkeleton } from "../../components/Feedback";
import { useToast } from "../../components/Toast";
import type { NotificationRuleRow, NotificationRulesResponse } from "../../types";

/** How the alerts are grouped on this screen. An alert listed in none of them goes under "Other". */
const GROUPS: { title: string; hint: string; events: string[] }[] = [
  {
    title: "Work and handovers", hint: "When work reaches someone, or comes back to them",
    events: ["WORK_ASSIGNED", "READY_FOR_TESTING", "REVIEW_NAMED", "REVIEW_OPEN", "RETURNED", "HOLDS"],
  },
  { title: "Failures and retests", hint: "The moment a result fails, and what is decided after", events: ["FAILED_RESULT", "RETESTS"] },
  { title: "Due dates", hint: "Checked once an hour", events: ["DUE_SOON", "OVERDUE"] },
  { title: "Certificates", hint: "At the last signature", events: ["CERT_RELEASED"] },
  { title: "Lab records", hint: "Checked once an hour", events: ["CALIBRATION_DUE", "QUALIFICATION_DUE"] },
];

type Patch = Partial<NotificationRuleRow>;

/** A number of days, saved when the person leaves the box or presses Enter. The server checks the range. */
function Days({ value, label, disabled, onSave }: {
  value: number;
  label: string;
  disabled: boolean;
  onSave: (days: number) => void;
}) {
  const [text, setText] = useState(String(value));
  // Once a save is over, show what is saved: the new number, or the old one if it was refused.
  useEffect(() => {
    if (!disabled) setText(String(value));
  }, [value, disabled]);

  const commit = () => {
    if (text.trim() === "") setText(String(value));
    else if (Number(text) !== value) onSave(Number(text));
  };

  return (
    <input
      type="number" className="alert-days" min={0} max={60} value={text} disabled={disabled} aria-label={label}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
    />
  );
}

function RuleRow({ rule, roles, emailReady, busy, onSave }: {
  rule: NotificationRuleRow;
  roles: NotificationRulesResponse["roles"];
  emailReady: boolean;
  busy: boolean;
  onSave: (patch: Patch) => void;
}) {
  const on = rule.enabled;
  return (
    <li className={`alert-row ${on ? "" : "off"}`}>
      <div className="alert-main">
        <div className="alert-text">
          <b>{rule.label}</b>
          <span className="cell-sub">{rule.hint}</span>
        </div>
        <label className="switch-field">
          <span>{on ? "On" : "Off"}</span>
          <input
            type="checkbox" role="switch" className="switch" checked={on} disabled={busy} aria-label={rule.label}
            onChange={(e) => onSave({ enabled: e.target.checked })}
          />
        </label>
      </div>

      {on && (
        <div className="alert-settings">
          <div className="alert-setting">
            <span className="alert-setting-name">Sent</span>
            <span className="chip-toggle fixed" title="Every alert reaches the bell">✓ In the app</span>
            <button type="button" className="chip-toggle" aria-pressed={rule.email} disabled={busy}
              onClick={() => onSave({ email: !rule.email })}>
              {rule.email && "✓ "}By email
            </button>
            {!emailReady && rule.email && <span className="cell-sub">once a mail server is set up</span>}
          </div>

          {(rule.takes_days_before || rule.takes_repeat) && (
            <div className="alert-setting">
              <span className="alert-setting-name">When</span>
              {rule.takes_days_before && (
                <span className="alert-inline">
                  Warn
                  <Days value={rule.days_before} label="Days before" disabled={busy}
                    onSave={(days) => onSave({ days_before: days })} />
                  days before
                </span>
              )}
              {rule.takes_repeat && (
                <span className="alert-inline">
                  Remind again every
                  <Days value={rule.repeat_days} label="Remind again every so many days" disabled={busy}
                    onSave={(days) => onSave({ repeat_days: days })} />
                  days <span className="cell-sub">(0 = only once)</span>
                </span>
              )}
            </div>
          )}

          {rule.takes_roles && (
            <div className="alert-setting">
              <span className="alert-setting-name">Also tell</span>
              {roles.map((role) => {
                const picked = rule.role_ids.includes(role.id);
                return (
                  <button key={role.id} type="button" className="chip-toggle" aria-pressed={picked} disabled={busy}
                    onClick={() => onSave({
                      role_ids: picked ? rule.role_ids.filter((id) => id !== role.id) : [...rule.role_ids, role.id],
                    })}>
                    {picked && "✓ "}{role.name}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

/** Which alerts go out, and who else hears them. Every change is on the record. */
export default function NotificationRules() {
  const toast = useToast();
  const [data, setData] = useState<NotificationRulesResponse | null>(null);
  const [error, setError] = useState("");
  const [testing, setTesting] = useState(false);
  // One change at a time per alert: each save sends the whole rule.
  const [saving, setSaving] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await apiGet<NotificationRulesResponse>("/api/notification-rules/"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the rules.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (rule: NotificationRuleRow, patch: Patch) => {
    setSaving(rule.event);
    try {
      const saved = await apiPut<NotificationRuleRow>(`/api/notification-rules/${rule.event}/`, { ...rule, ...patch });
      setData((d) => d && { ...d, rules: d.rules.map((r) => (r.event === rule.event ? saved : r)) });
      toast("ok", patch.enabled === undefined ? `${rule.label}: saved` : `${rule.label}: turned ${patch.enabled ? "on" : "off"}`);
    } catch (err) {
      toast("error", "Not saved", err instanceof Error ? err.message : undefined);
      void load();
    } finally {
      setSaving(null);
    }
  };

  const sendTest = async () => {
    setTesting(true);
    try {
      const { to } = await apiPost<{ to: string }>("/api/notification-rules/test-email/");
      toast("ok", "Test email sent", `Check the inbox of ${to}.`);
    } catch (err) {
      toast("error", "Test email not sent", err instanceof Error ? err.message : undefined);
    } finally {
      setTesting(false);
    }
  };

  if (error) return <Message kind="error">{error}</Message>;
  if (!data) return <div className="card"><div className="card-body flush"><TableSkeleton /></div></div>;

  const listed = new Set(GROUPS.flatMap((g) => g.events));
  const groups = GROUPS.map((g) => ({ ...g, rules: data.rules.filter((r) => g.events.includes(r.event)) }));
  const other = data.rules.filter((r) => !listed.has(r.event));
  if (other.length) groups.push({ title: "Other", hint: "", events: [], rules: other });
  const onCount = data.rules.filter((r) => r.enabled).length;

  return (
    <>
      <div className="page-head">
        <h1>Notification rules</h1>
        <p className="sub">
          Which alerts go out, and who else hears them. Every alert appears in the bell inside the app, and by
          email for people with an address. {onCount} of {data.rules.length} alerts are on.
        </p>
      </div>

      {data.email_ready ? (
        <div className="actions-bar" style={{ marginBottom: 16 }}>
          <button className="ghost small" disabled={testing} onClick={() => void sendTest()}>
            {testing ? "Sending…" : "Send me a test email"}
          </button>
          <span className="cell-sub">It goes to the address on your own account.</span>
        </div>
      ) : (
        <div style={{ marginBottom: 16 }}>
          <Message kind="info">
            Email is off until a mail server is set up. Every alert still reaches the bell, and the email choices
            below take effect once it is.
          </Message>
        </div>
      )}

      {groups.filter((g) => g.rules.length > 0).map((g) => {
        const on = g.rules.filter((r) => r.enabled).length;
        return (
          <section className="card" key={g.title} aria-label={g.title}>
            <div className="card-head">
              <h2>{g.title}</h2>
              {g.hint && <span className="hint">{g.hint}</span>}
              <div className="spacer" />
              <span className={`badge ${on ? "info" : "muted"}`}>{on} of {g.rules.length} on</span>
            </div>
            <ul className="alert-list">
              {g.rules.map((rule) => (
                <RuleRow
                  key={rule.event} rule={rule} roles={data.roles} emailReady={data.email_ready}
                  busy={saving === rule.event} onSave={(patch) => void save(rule, patch)}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </>
  );
}
