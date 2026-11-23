import { useAuth } from "../auth";

/**
 * The lab's mark: its own logo once one is uploaded in Settings, otherwise a
 * two-tone capsule. Decorative — the lab name always sits beside it as text.
 */
export default function BrandMark({ size = 34 }: { size?: number }) {
  const { titles } = useAuth();
  if (titles.logo_url) {
    return (
      <div className="brand-mark logo" style={{ width: size, height: size }} aria-hidden="true">
        <img src={titles.logo_url} alt="" />
      </div>
    );
  }
  return (
    <div className="brand-mark" style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 40 40" width={size * 0.82} height={size * 0.82}>
        <g transform="rotate(-38 20 20)">
          <rect x="3" y="12.5" width="34" height="15" rx="7.5" fill="#ffffff" />
          <path d="M20 12.5h9.5a7.5 7.5 0 0 1 0 15H20z" fill="#fdba74" />
          <rect x="7.5" y="15.2" width="9" height="3" rx="1.5" fill="#fff" opacity="0.5" />
          <path d="M20 12.5v15" stroke="#fff" strokeOpacity="0.55" strokeWidth="1.2" />
        </g>
      </svg>
    </div>
  );
}
