import type { SiteStats } from "@/lib/api";
import { insightAsOfLine } from "@/lib/insightHeadline";

export interface CounterRow {
  key: string;
  value: number;
  label: string;
  title: string | null;     // the hover: only the date the count rests on ("As of Oct 1, 2026"; the chain count adds its source)
}

/** The four homepage counters, each a live count from a stored table, dated by its own newest row. Labels as written. */
export function counterRows(stats: SiteStats | null): CounterRow[] {
  if (!stats) return [];
  const contractsAsOf = insightAsOfLine(stats.option_contracts_as_of);
  return [
    { key: "contracts", value: stats.option_contracts_captured, label: "option contracts captured nightly",
      title: contractsAsOf ? `${contractsAsOf} (${stats.option_contracts_source})` : null },
    { key: "prices", value: stats.licensed_daily_prices, label: "licensed daily prices", title: insightAsOfLine(stats.licensed_daily_prices_as_of) },
    { key: "earnings", value: stats.earnings_reports_measured, label: "earnings reactions measured", title: insightAsOfLine(stats.earnings_reports_as_of) },
    { key: "analyst", value: stats.analyst_reactions_measured, label: "analyst actions measured", title: insightAsOfLine(stats.analyst_reactions_as_of) },
  ];
}


// ── Layout model ───────────────────────────────────────────────────────────────
// The counters row's geometry, stated once. SiteCounters.tsx and page.tsx carry the same numbers as Tailwind classes and
// a clamp() rule; __tests__/siteCounters.test.ts asserts those strings match this model and that four 7-character
// numbers never overlap at 1024, 1280 and 1440 pixels. Glyph widths are the display face's measured averages.

export const COUNTER_LAYOUT = {
  containerMax: 1152,        // max-w-6xl
  sidePadding: { base: 16, sm: 24 },   // px-4 sm:px-6 on the counters section
  columns: { base: 1, sm: 2, lg: 4 },  // grid-cols-1 sm:grid-cols-2 lg:grid-cols-4
  breakpoints: { sm: 640, lg: 1024 },
  gapX: 20,                  // gap-x-5
  font: { min: 36, vw: 4.2, max: 60 },   // clamp(36px, 4.2vw, 60px) on .stat-number
  digitEm: 0.6,              // tabular digit advance in the display face, bold
  commaEm: 0.28,
  label: { fontPx: 10, trackingEm: 0.08 },   // text-[10px] tracking-[.08em], mono
  monoCharEm: 0.6,
} as const;

export const STAT_NUMBER_CLAMP = `clamp(${COUNTER_LAYOUT.font.min}px, ${COUNTER_LAYOUT.font.vw}vw, ${COUNTER_LAYOUT.font.max}px)`;

export interface CounterGeometry {
  columns: number;
  columnWidth: number;
  fontSize: number;
  /** Each number's horizontal box [left, right] within the row, centered in its column. */
  boxes: Array<[number, number]>;
}

export function numberWidth(text: string, fontSize: number): number {
  let em = 0;
  for (const ch of text) em += ch === "," || ch === "." ? COUNTER_LAYOUT.commaEm : COUNTER_LAYOUT.digitEm;
  return em * fontSize;
}

export function labelWidth(text: string): number {
  const { fontPx, trackingEm } = COUNTER_LAYOUT.label;
  return text.length * (fontPx * COUNTER_LAYOUT.monoCharEm + fontPx * trackingEm);
}

/** The row at a viewport width: columns, column width, font size and each number's box. Pure. */
export function counterGeometry(viewport: number, numbers: string[]): CounterGeometry {
  const L = COUNTER_LAYOUT;
  const columns = viewport >= L.breakpoints.lg ? L.columns.lg : viewport >= L.breakpoints.sm ? L.columns.sm : L.columns.base;
  const padding = viewport >= L.breakpoints.sm ? L.sidePadding.sm : L.sidePadding.base;
  const rowWidth = Math.min(L.containerMax, viewport - 2 * padding);
  const columnWidth = (rowWidth - L.gapX * (columns - 1)) / columns;
  const fontSize = Math.min(L.font.max, Math.max(L.font.min, (L.font.vw / 100) * viewport));
  const boxes = numbers.map((n, i) => {
    const col = i % columns;
    const left = col * (columnWidth + L.gapX);
    const w = numberWidth(n, fontSize);
    const start = left + (columnWidth - w) / 2;
    return [start, start + w] as [number, number];
  });
  return { columns, columnWidth, fontSize, boxes };
}

/** True when two boxes on the same grid row share any horizontal span. */
export function boxesOverlap(a: [number, number], b: [number, number]): boolean {
  return a[0] < b[1] && b[0] < a[1];
}
