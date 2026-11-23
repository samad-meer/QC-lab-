const UP = "M6 15l6-6 6 6";
const DOWN = "M6 9l6 6 6-6";
const TRASH = "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3";

function Glyph({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * Move up, move down and remove, for one row of a list being edited: a stage, a
 * step, a check point, a sign-off column. One quiet group; removing turns red only
 * when pointed at. Without onUp or onDown (first or last row) that arrow is dimmed.
 */
export default function RowTools({ noun, n, onUp, onDown, onRemove, canRemove = true, moves = true }: {
  /** What the row is, for the buttons' names: "step", "check point", "sign-off". */
  noun: string;
  n: number;
  onUp?: () => void;
  onDown?: () => void;
  onRemove: () => void;
  canRemove?: boolean;
  /** False for a row that is removed but never moved, such as a check point. */
  moves?: boolean;
}) {
  return (
    <div className={`row-tools${moves ? "" : " solo"}`} role="group" aria-label={`${noun} ${n}`}>
      {moves && (
        <>
          <button type="button" className="rt-btn" disabled={!onUp} onClick={onUp}
            aria-label={`Move ${noun} ${n} up`} title="Move up"><Glyph d={UP} /></button>
          <button type="button" className="rt-btn" disabled={!onDown} onClick={onDown}
            aria-label={`Move ${noun} ${n} down`} title="Move down"><Glyph d={DOWN} /></button>
          <span className="rt-sep" aria-hidden="true" />
        </>
      )}
      <button type="button" className="rt-btn rt-remove" disabled={!canRemove} onClick={onRemove}
        aria-label={`Remove ${noun} ${n}`} title={canRemove ? `Remove ${noun}` : `A ${noun} cannot be removed here`}>
        <Glyph d={TRASH} />
      </button>
    </div>
  );
}
