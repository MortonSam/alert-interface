import type { SiteStats } from "@/lib/api";
import { insightAsOfLine } from "@/lib/insightHeadline";

export interface CounterRow {
  key: string;
  value: number;
  label: string;
  title: string | null;     // the hover: only the date the count rests on ("As of Oct 1, 2026"; the chain count adds its source)
}

export const PRICES_HOVER = "Five years of daily prices for every S&P 500 stock, licensed from Intrinio";

/** The four counters' keys and labels, as written, for the row that has no counts to show yet. */
export const COUNTER_LABELS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "contracts", label: "option contracts captured nightly" },
  { key: "prices", label: "daily stock prices on record" },
  { key: "earnings", label: "earnings reactions measured" },
  { key: "analyst", label: "analyst actions measured" },
];

/** The four homepage counters, each a live count from a stored table, dated by its own newest row. Labels as written. */
export function counterRows(stats: SiteStats | null): CounterRow[] {
  if (!stats) return [];
  const contractsAsOf = insightAsOfLine(stats.option_contracts_as_of);
  const label = (key: string) => COUNTER_LABELS.find((l) => l.key === key)!.label;
  return [
    { key: "contracts", value: stats.option_contracts_captured, label: label("contracts"),
      title: contractsAsOf ? `${contractsAsOf} (${stats.option_contracts_source})` : null },
    { key: "prices", value: stats.licensed_daily_prices, label: label("prices"),
      title: [PRICES_HOVER, insightAsOfLine(stats.licensed_daily_prices_as_of)].filter(Boolean).join(" · ") },
    { key: "earnings", value: stats.earnings_reports_measured, label: label("earnings"), title: insightAsOfLine(stats.earnings_reports_as_of) },
    { key: "analyst", value: stats.analyst_reactions_measured, label: label("analyst"), title: insightAsOfLine(stats.analyst_reactions_as_of) },
  ].filter((r): r is CounterRow => r.value != null);      // a count the API withholds (personal-use source, backend services/personal_use) is left out
}


// ── Layout model ───────────────────────────────────────────────────────────────
// The counters row's geometry, stated once (2026-10-20: at 1440 the four figures ran together, "154,237671,7349,932", because
// the old model took the row as 1024px when max-w-5xl includes its 32px side padding, so 60px figures overflowed 228px columns).
// The row is a size container: the grid is four across only when the row is at least FOUR_ACROSS_MIN_PX wide, otherwise 2x2,
// columns are GAP_PX apart, and each figure's size is the column width over the longest figure's width in ems (--num-em, set by
// SiteCounters from the values shown), capped at FONT_MAX_PX, so a figure always fits its column. Across, the grid has one column
// per count shown (2026-10-29: with the analyst count withheld, three counts in four columns sat left of centre), and two by two an
// odd last count spans the row, centred. page.tsx's CSS carries these
// numbers (tested); __tests__/siteCounters.test.ts holds the geometry at 360 to 1920 and the real-Chrome check measures it.

export const COUNTER_LAYOUT = {
  containerMax: 1024,        // max-w-5xl on the home column, padding included
  sidePadding: { base: 16, sm: 32 },   // px-4 sm:px-8 on that column
  breakpoints: { sm: 640 },
  gapPx: 48,                 // column-gap on .counters-grid
  fourAcrossMinPx: 800,      // the row's own width (container query) from which four columns fit
  fontMaxPx: 60,
  digitEm: 0.631,            // tabular digit advance in the display face (Newsreader 600), measured in Chrome at 60px
  commaEm: 0.241,
  safety: 1.06,              // the figure's width in ems is padded by this before sizing, so rounding never makes it touch
  label: { fontPx: 10, trackingEm: 0.08 },   // text-[10px] tracking-[.08em], mono; labels wrap inside their column
  monoCharEm: 0.6,
} as const;

/** The longest figure's width in ems, padded: the --num-em the CSS divides the column by. */
export function numEm(texts: string[]): number {
  const em = (t: string) => [...t].reduce((a, ch) => a + (ch === "," || ch === "." ? COUNTER_LAYOUT.commaEm : COUNTER_LAYOUT.digitEm), 0);
  return Number((Math.max(1, ...texts.map(em)) * COUNTER_LAYOUT.safety).toFixed(3));
}

export interface CounterGeometry {
  columns: number;
  columnWidth: number;
  fontSize: number;
  /** Each number's horizontal box [left, right] within the row, left-aligned in its column. */
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

/** The row's own width at a viewport width: the home column's content box. */
export function rowWidth(viewport: number): number {
  const L = COUNTER_LAYOUT;
  const padding = viewport >= L.breakpoints.sm ? L.sidePadding.sm : L.sidePadding.base;
  return Math.min(L.containerMax, viewport) - 2 * padding;
}

/** The row at a viewport width, as the CSS lays it out: columns, column width, font size and each number's box. Pure. */
export function counterGeometry(viewport: number, numbers: string[]): CounterGeometry {
  const L = COUNTER_LAYOUT;
  const row = rowWidth(viewport);
  const columns = row >= L.fourAcrossMinPx ? Math.max(1, Math.min(4, numbers.length)) : 2;
  const columnWidth = (row - L.gapPx * (columns - 1)) / columns;
  const fontSize = Math.min(L.fontMaxPx, columnWidth / numEm(numbers));
  const boxes = numbers.map((n, i) => {
    const alone = columns === 2 && i === numbers.length - 1 && i % 2 === 0;    // the odd last count, two by two: centred across the row
    const left = alone ? (row - numberWidth(n, fontSize)) / 2 : (i % columns) * (columnWidth + L.gapPx);
    return [left, left + numberWidth(n, fontSize)] as [number, number];
  });
  return { columns, columnWidth, fontSize, boxes };
}

/** True when two boxes on the same grid row share any horizontal span. */
export function boxesOverlap(a: [number, number], b: [number, number]): boolean {
  return a[0] < b[1] && b[0] < a[1];
}

/** The page's CSS for the row, from the model. */
export const COUNTER_CSS = `
        .counters { container-type: inline-size; }
        .counters-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: ${COUNTER_LAYOUT.gapPx}px; row-gap: 40px; }
        .counters-grid > :last-child:nth-child(odd) { grid-column: 1 / -1; }
        .stat-number {
          font-size: min(${COUNTER_LAYOUT.fontMaxPx}px, calc((100cqw - ${COUNTER_LAYOUT.gapPx}px) / 2 / var(--num-em, 4.3)));
          line-height: 1;
          letter-spacing: -.01em;
          font-variant-numeric: tabular-nums;
        }
        @container (min-width: ${COUNTER_LAYOUT.fourAcrossMinPx}px) {${[1, 2, 3, 4].map((n) => `
          .counters-grid[data-n="${n}"] { grid-template-columns: repeat(${n}, minmax(0, 1fr)); }
          .counters-grid[data-n="${n}"] .stat-number { font-size: min(${COUNTER_LAYOUT.fontMaxPx}px, calc((100cqw - ${(n - 1) * COUNTER_LAYOUT.gapPx}px) / ${n} / var(--num-em, 4.3))); }`).join("")}
          .counters-grid > :last-child:nth-child(odd) { grid-column: auto; }
        }`;
