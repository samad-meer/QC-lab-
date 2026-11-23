/** Line icons for the print group, drawn like the rest of the app's (24 grid, 2 px stroke). */
const PRINTER = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M6 9V3h12v6" />
    <rect x="3" y="9" width="18" height="8" rx="2" />
    <path d="M7 14h10v7H7z" />
  </svg>
);
const ICONS = {
  // A tag: the sticker that goes on the container.
  label: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z" />
      <circle cx="8" cy="8" r="1.5" />
    </svg>
  ),
  // A page with lines: the full record.
  record: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
      <path d="M14 3v5h5M9 13h6M9 17h6" />
    </svg>
  ),
};

export interface PrintItem {
  /** Shown on the button: "Label", "Batch record". */
  label: string;
  href: string;
  icon: keyof typeof ICONS;
  /** What it prints, shown on hover. */
  hint: string;
}

/**
 * What a page can print, as one group: a printer, then each document. Each opens
 * its printable page in a new tab.
 */
export default function PrintLinks({ items }: { items: PrintItem[] }) {
  return (
    <div className="print-group" role="group" aria-label="Print">
      <span className="print-group-lead" aria-hidden="true">{PRINTER}Print</span>
      {items.map((it) => (
        <a key={it.href} href={it.href} target="_blank" rel="noreferrer"
          title={`${it.hint} Opens in a new tab.`} aria-label={`Print ${it.label.toLowerCase()}`}>
          {ICONS[it.icon]}
          {it.label}
        </a>
      ))}
    </div>
  );
}
