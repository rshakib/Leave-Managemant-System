// Tiny inline SVG icon set — no icon library, no new dependency.
const PATHS = {
  home: 'M3 10.5 12 3l9 7.5M5.5 9.5V20h13V9.5',
  sun: 'M12 4V2M12 22v-2M4 12H2M22 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z',
  balance: 'M12 3v18M5 7h14M7 7l-3 6h6L7 7Zm10 0-3 6h6l-3-6ZM8 20h8',
  plus: 'M12 5v14M5 12h14',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  calendar: 'M8 3v3M16 3v3M4 8h16M4 6h16v15H4zM4 11h16',
  check: 'M9 11.5 11.5 14 15.5 9.5M5 4h14v16H5z',
  chart: 'M4 20V4M4 20h16M8 16v-4M12 16V7M16 16v-6',
  users: 'M16 20v-1.5A3.5 3.5 0 0 0 12.5 15h-5A3.5 3.5 0 0 0 4 18.5V20M10 12a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm10 8v-1.5a3.5 3.5 0 0 0-2.6-3.4M15.5 5.2a3.5 3.5 0 0 1 0 6.6',
  workflow: 'M4 6h6v5H4zM14 13h6v5h-6zM7 11v3a3 3 0 0 0 3 3h4',
  sliders: 'M5 7h14M5 12h14M5 17h14M9 5v4M15 10v4M11 15v4',
  building: 'M4 21V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v16M14 9h4a2 2 0 0 1 2 2v10M3 21h18M7 7h2M7 11h2M7 15h2',
  layers: 'M12 3 3 8l9 5 9-5-9-5Zm-9 8 9 5 9-5M3 16l9 5 9-5',
  tag: 'M20.5 13.5 12 22l-9-9V4h9l8.5 8.5ZM7.5 7.5h.01',
  mail: 'M3 6h18v12H3zM3 7l9 6 9-6',
  shield: 'M12 3l7 3v6c0 4.2-2.8 7.6-7 9-4.2-1.4-7-4.8-7-9V6l7-3Zm-2.5 9 2 2 4-4',
  logout: 'M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 8l-4 4 4 4M6 12h10',
  menu: 'M4 7h16M4 12h16M4 17h16',
  close: 'M6 6l12 12M18 6 6 18',
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm10 2-4.35-4.35',
  download: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
  refresh: 'M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5',
  lock: 'M7 11V7a5 5 0 0 1 10 0v4M5 11h14v10H5z',
  arrowLeft: 'M19 12H5M12 19l-7-7 7-7',
  alertCircle: 'M12 2a10 10 0 1 0 0 20 10 10 0 1 0 0-20ZM12 8v4M12 16h.01',
}

export default function Icon({ name, size = 18, className }) {
  const path = PATHS[name] ?? PATHS.home
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={path} />
    </svg>
  )
}
