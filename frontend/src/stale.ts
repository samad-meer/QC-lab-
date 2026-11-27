/**
 * The last answer a page had, kept for this browser tab only, so the page can show it at once while it
 * asks again. It is shown as what it is: the page says it is updating until the fresh answer replaces it.
 * Kept per person: whatever another person left in this tab is cleared the first time someone else's is
 * kept. A tab that cannot store anything (private windows, blocked storage) simply waits as before.
 */
const PREFIX = "qclab-last:";

export function remembered<T>(who: number | undefined, key: string): T | undefined {
  if (who === undefined) return undefined;
  try {
    const raw = window.sessionStorage.getItem(`${PREFIX}${who}:${key}`);
    return raw ? (JSON.parse(raw) as { data: T }).data : undefined;
  } catch {
    return undefined;
  }
}

export function remember(who: number | undefined, key: string, data: unknown): void {
  if (who === undefined) return;
  try {
    const mine = `${PREFIX}${who}:`;
    for (let i = window.sessionStorage.length - 1; i >= 0; i -= 1) {
      const name = window.sessionStorage.key(i);
      if (name && name.startsWith(PREFIX) && !name.startsWith(mine)) window.sessionStorage.removeItem(name);
    }
    window.sessionStorage.setItem(`${mine}${key}`, JSON.stringify({ at: Date.now(), data }));
  } catch {
    /* full or blocked: next time the page waits, as it always did */
  }
}
