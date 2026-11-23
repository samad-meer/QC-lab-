let labZone: string | undefined;
// A 12-hour clock (02:05 PM) unless the lab chose 24 hours (14:05) in Settings.
let labHour12 = true;

/** Set from the server, so a screen shows what the paper shows, wherever the browser thinks it is. */
export function setLabZone(zone: string | undefined) {
  labZone = zone;
}

/** "12h" or "24h", from Settings: how every time of day is written. */
export function setLabClock(format: string | undefined) {
  labHour12 = format !== "24h";
}

function parts(when: Date, options: Intl.DateTimeFormatOptions) {
  const found: Record<string, string> = {};
  for (const p of new Intl.DateTimeFormat("en-GB", options).formatToParts(when)) found[p.type] = p.value;
  return found;
}

/** A time of day on the lab's clock: 02:05:12 PM, or 14:05:12. */
function clockOf(when: Date, zone: string | undefined, hour12: boolean, seconds = true) {
  const p = parts(when, {
    day: "2-digit", month: "short", year: "numeric", weekday: "long",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: hour12 ? "h12" : "h23", timeZone: zone,
  });
  const time = `${p.hour}:${p.minute}${seconds ? `:${p.second}` : ""}${hour12 ? ` ${(p.dayPeriod ?? "").toUpperCase()}` : ""}`;
  return { p, time };
}

/**
 * The exact date and time, to the second, as every report and certificate writes it:
 * 30-Oct-2026 02:05:12 PM, or 30-Oct-2026 14:05:12 on a 24-hour clock. In the lab's
 * time zone and clock, or in `zone` and `hour12` where a screen previews others (Settings).
 */
export function fmtDateTime(iso: string, zone: string | undefined = labZone, hour12: boolean = labHour12): string {
  const { p, time } = clockOf(new Date(iso), zone, hour12);
  return `${p.day}-${p.month}-${p.year} ${time}`;
}

/** The time now on the lab's clock, and the date written out: for the dashboard. */
export function fmtNow(now: Date): { time: string; date: string; hour: number } {
  const { p, time } = clockOf(now, labZone, labHour12);
  const hour = Number(parts(now, { hour: "2-digit", hourCycle: "h23", timeZone: labZone }).hour);
  return { time, date: `${p.weekday}, ${Number(p.day)} ${p.month} ${p.year}`, hour };
}

/** “UTC+05:00”: how far a time zone is from UTC right now. */
export function zoneOffset(zone: string): string {
  const name = parts(new Date(), { timeZone: zone, timeZoneName: "longOffset" }).timeZoneName ?? "";
  return name === "GMT" ? "UTC+00:00" : name.replace("GMT", "UTC");
}

export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

export function fmtDate(iso: string): string {
  // A date with no time is that date, in any time zone.
  const dateOnly = iso.length === 10;
  const p = parts(new Date(dateOnly ? `${iso}T00:00:00Z` : iso), {
    day: "2-digit", month: "short", year: "numeric", timeZone: dateOnly ? "UTC" : labZone,
  });
  return `${p.day}-${p.month}-${p.year}`;
}

/** Whole days from the lab's today until a due date — negative once overdue. */
export function daysUntil(due: string): number {
  const d = new Date(`${due}T00:00:00Z`);
  const today = new Date(`${todayInput()}T00:00:00Z`);
  return Math.round((d.getTime() - today.getTime()) / 86_400_000);
}

/**
 * Now, in the lab's time zone, as <input type="datetime-local"> wants it. Sent as it
 * stands: the server reads a time with no zone as the lab's, wherever the computer is.
 */
export function nowLocalInput(): string {
  const p = parts(new Date(), {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    hourCycle: "h23", timeZone: labZone,
  });
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

/** A recorded moment, in the lab's time zone, as <input type="datetime-local"> wants it. */
export function toLocalInput(iso: string): string {
  const p = parts(new Date(iso), {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    hourCycle: "h23", timeZone: labZone,
  });
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

/** The lab's today, as <input type="date"> wants it. Date fields start filled in. */
export function todayInput(): string {
  return nowLocalInput().slice(0, 10);
}
