/** Small shared pieces for loading, emptiness and inline messages. */

export function Message({
  kind,
  children,
}: {
  kind: "error" | "warn" | "ok" | "info";
  children: React.ReactNode;
}) {
  const icon = kind === "error" ? "!" : kind === "warn" ? "!" : kind === "ok" ? "✓" : "i";
  return (
    <div className={`msg ${kind}`} role={kind === "error" ? "alert" : undefined}>
      <span className="msg-icon" aria-hidden="true">{icon}</span>
      <div>{children}</div>
    </div>
  );
}

export function EmptyState({
  icon = "○",
  title,
  sub,
}: {
  icon?: string;
  title: string;
  sub?: string;
}) {
  return (
    <div className="empty">
      <div className="empty-icon" aria-hidden="true">{icon}</div>
      <div className="empty-title">{title}</div>
      {sub && <div className="empty-sub">{sub}</div>}
    </div>
  );
}

export function TableSkeleton({ rows = 4, cols = 5 }: { rows?: number; cols?: number }) {
  const widths = ["22%", "34%", "18%", "26%", "20%", "16%", "24%"];
  return (
    <div aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, r) => (
        <div className="sk-row" key={r}>
          {Array.from({ length: cols }).map((_, c) => (
            <div className="sk" key={c} style={{ width: widths[(r + c) % widths.length], flex: "0 0 auto" }} />
          ))}
        </div>
      ))}
    </div>
  );
}
