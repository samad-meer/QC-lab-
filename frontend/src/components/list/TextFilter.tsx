import { useEffect, useRef, useState } from "react";

const SETTLE_MS = 300;

/** A typed filter: it applies once typing pauses, not on every keystroke. */
export default function TextFilter({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
}) {
  const [text, setText] = useState(value);
  const settling = useRef<number | undefined>(undefined);

  useEffect(() => setText(value), [value]);
  useEffect(() => () => window.clearTimeout(settling.current), []);

  return (
    <label className="field">
      {label}
      <input
        value={text}
        placeholder={placeholder}
        onChange={(e) => {
          const next = e.target.value;
          setText(next);
          window.clearTimeout(settling.current);
          settling.current = window.setTimeout(() => onChange(next), SETTLE_MS);
        }}
      />
    </label>
  );
}
