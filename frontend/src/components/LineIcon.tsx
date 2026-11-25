/** Line icons on a 24 grid, drawn like the rest of the app's (2 px stroke, round ends). */
export const ICONS = {
  inbox: "M22 12h-6l-2 3h-4l-2-3H2M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z",
  handoff: "M5 12h14M13 6l6 6-6 6",
  back: "M9 14 4 9l5-5M4 9h11a5 5 0 0 1 0 10h-1",
  sign: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
  flask: "M9 3h6M10 3v6l-5.5 9.5A1.5 1.5 0 0 0 5.8 21h12.4a1.5 1.5 0 0 0 1.3-2.5L14 9V3",
  retest: "M21 4v6h-6M3 20v-6h6M5.5 9a8 8 0 0 1 13.2-3L21 10M3 14l2.3 4A8 8 0 0 0 18.5 15",
  people: "M16 19c0-2.8-1.8-5-4-5s-4 2.2-4 5M12 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6M20 18c0-2-1-3.6-2.5-4.4M17 5.2a3 3 0 0 1 0 5.6",
  record: "M9 4h6a1 1 0 0 1 1 1v1H8V5a1 1 0 0 1 1-1M8 6H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-2M9 13h6M9 17h4",
  list: "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01",
  board: "M4 4h5v16H4zM10.5 4h5v10h-5zM17 4h3v7h-3z",
  box: "M21 8l-9-5-9 5 9 5 9-5M3 8v8l9 5 9-5V8M12 13v8",
  book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  flow: "M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6M18 9a9 9 0 0 1-9 9",
  door: "M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3",
  check: "M20 6 9 17l-5-5",
  alert: "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0",
  bell: "M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0",
  clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20M12 6v6l4 2",
  send: "M22 2 11 13M22 2l-7 20-4-9-9-4z",
  pause: "M10 4H6v16h4zM18 4h-4v16h4z",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16M21 21l-4.3-4.3",
  close: "M18 6 6 18M6 6l12 12",
};
export type IconName = keyof typeof ICONS;

export default function LineIcon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name]} />
    </svg>
  );
}
