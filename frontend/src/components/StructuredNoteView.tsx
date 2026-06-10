"use client";

import { cn } from "@/lib/utils";
import type { StructuredNote, StructuredNoteItem, StructuredNoteFinancials } from "@/lib/api";
import Tip from "@/components/Tip";

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtCap(n: number): string {
  if (n >= 1e12) return `$${(n / 1e12).toFixed(1)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toLocaleString()}`;
}

function fmtRevenue(n: number): string {
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toLocaleString()}`;
}

function isPositive(s: string): boolean {
  const n = parseFloat(s.replace(/[^0-9.\-+]/g, ""));
  return !isNaN(n) && n > 0;
}

function isNegative(s: string): boolean {
  const n = parseFloat(s.replace(/[^0-9.\-+]/g, ""));
  return !isNaN(n) && n < 0;
}

function fmtMultiple(v: number | null): string | null {
  if (v == null) return null;
  return `${v.toFixed(1)}\u00d7`;
}

function fmtPct(v: number | null): string | null {
  if (v == null) return null;
  return `${v.toFixed(1)}%`;
}

function fmtPctSigned(v: number | null): string | null {
  if (v == null) return null;
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function fmtPeg(v: number | null): string | null {
  if (v == null) return null;
  return v.toFixed(1);
}

// ── Color configs ────────────────────────────────────────────────────────────

const sectionColors = {
  about: {
    dot: "bg-cool",
    label: "text-cool",
    accent: "border-l-cool/30",
    bg: "bg-cool/[0.04]",
  },
  highlights: {
    dot: "bg-success",
    label: "text-success",
    accent: "border-l-success/30",
    bg: "bg-success/[0.04]",
  },
  watch: {
    dot: "bg-amber-400",
    label: "text-amber-400",
    accent: "border-l-amber-400/30",
    bg: "bg-amber-400/[0.04]",
  },
  risks: {
    dot: "bg-destructive",
    label: "text-destructive",
    accent: "border-l-destructive/30",
    bg: "bg-destructive/[0.04]",
  },
  neutral: {
    dot: "bg-muted-foreground/60",
    label: "text-muted-foreground",
    accent: "border-l-muted-foreground/20",
    bg: "bg-muted-foreground/[0.04]",
  },
} as const;

// ── Metric tooltips ──────────────────────────────────────────────────────────

const METRIC_TIPS: Record<string, string> = {
  forward_pe:
    "Forward P/E \u2014 the stock price divided by next year's expected earnings. Lower means you're paying less per dollar of future profit.",
  pe_ttm:
    "Trailing P/E \u2014 stock price divided by the last 12 months of actual earnings. Useful as a reality check against the forward estimate.",
  ps_ttm:
    "Price-to-Sales \u2014 market cap divided by trailing 12-month revenue. Helpful for companies that aren't yet profitable.",
  peg_ttm:
    "PEG Ratio \u2014 the P/E divided by the earnings growth rate. A PEG near 1 suggests the stock is fairly priced for its growth.",
  forward_peg:
    "Forward PEG \u2014 same idea as PEG but uses forward earnings estimates. Below 1 may signal undervaluation relative to expected growth.",
  gross_margin:
    "Gross Margin \u2014 revenue minus cost of goods sold, as a percentage. Shows how much the company keeps before operating expenses.",
  operating_margin:
    "Operating Margin \u2014 profit from core operations as a percentage of revenue, after subtracting both cost of goods and operating expenses.",
  net_margin:
    "Net Profit Margin \u2014 the bottom-line percentage of revenue that becomes actual profit after all costs, interest, and taxes.",
  revenue_growth:
    "Revenue Growth (YoY) \u2014 how much total revenue grew compared to the same period a year ago.",
  eps_growth:
    "EPS Growth (YoY) \u2014 how much earnings per share grew versus the same period last year.",
  roe:
    "Return on Equity \u2014 net income divided by shareholder equity. Measures how effectively the company turns invested capital into profit.",
};

// ── Sub-components ───────────────────────────────────────────────────────────

function RatingPill({ rating }: { rating: string }) {
  const valid = ["bullish", "neutral", "bearish"] as const;
  if (!valid.includes(rating as typeof valid[number])) return null;

  const styles = {
    bullish: "bg-success/10 text-success border-success/25",
    neutral: "bg-cool/10 text-cool border-cool/25",
    bearish: "bg-destructive/10 text-destructive border-destructive/25",
  } as const;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold tracking-wide",
        styles[rating as keyof typeof styles],
      )}
    >
      <span className="text-[8px]">{"\u25CF"}</span>
      {rating.charAt(0).toUpperCase() + rating.slice(1)}
    </span>
  );
}

function StatCell({
  label,
  value,
  sub,
  subColor,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  subColor?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">
        {label}
      </span>
      <span className="font-mono text-sm font-semibold text-foreground">
        {value}
      </span>
      {sub && (
        <span className={cn("text-[11px] text-muted-foreground", subColor)}>
          {sub}
        </span>
      )}
    </div>
  );
}

function MetricCell({
  label,
  tip,
  value,
  sub,
  subColor,
}: {
  label: string;
  tip?: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  subColor?: string;
}) {
  const labelEl = tip ? (
    <Tip text={tip}>
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60 border-b border-dotted border-muted-foreground/40">
        {label}
      </span>
    </Tip>
  ) : (
    <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">
      {label}
    </span>
  );

  return (
    <div className="flex flex-col gap-0.5">
      {labelEl}
      <span className="font-mono text-sm font-semibold text-foreground">
        {value}
      </span>
      {sub && (
        <span className={cn("text-[11px] text-muted-foreground", subColor)}>
          {sub}
        </span>
      )}
    </div>
  );
}

function SectionBlock({
  color,
  title,
  count,
  children,
}: {
  color: keyof typeof sectionColors;
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  const c = sectionColors[color];
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span className={cn("h-2 w-2 rounded-full", c.dot)} />
        <span
          className={cn("text-[11px] font-semibold uppercase tracking-wider", c.label)}
        >
          {title}
        </span>
        {count != null && count > 0 && (
          <span className="text-[11px] text-muted-foreground/50">
            {count} {count === 1 ? "point" : "points"}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

function ItemList({
  items,
  color,
}: {
  items: StructuredNoteItem[];
  color: keyof typeof sectionColors;
}) {
  const c = sectionColors[color];
  return (
    <div className="flex flex-col gap-3">
      {items.map((item, i) => (
        <div
          key={i}
          className={cn("border-l-2 pl-3.5 py-1", c.accent, c.bg, "rounded-r-md")}
        >
          <p className="text-[13px] font-semibold text-foreground leading-snug">
            {item.lead}
          </p>
          <p className="text-[13px] text-foreground/80 leading-[1.65] mt-0.5">
            {item.detail}
          </p>
        </div>
      ))}
    </div>
  );
}

// ── Financials blocks ────────────────────────────────────────────────────────

function ValuationBlock({ f }: { f: StructuredNoteFinancials }) {
  const hasFwdPe = f.forward_pe != null;
  const hasPs = f.ps_ttm != null;
  const hasPeg = f.peg_ttm != null;
  if (!hasFwdPe && !hasPs && !hasPeg) return null;

  return (
    <SectionBlock color="neutral" title="Valuation">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 rounded-lg bg-secondary/50 px-4 py-3">
        {hasFwdPe && (
          <MetricCell
            label="Fwd P/E"
            tip={METRIC_TIPS.forward_pe}
            value={fmtMultiple(f.forward_pe)}
            sub={f.pe_ttm != null ? `TTM ${fmtMultiple(f.pe_ttm)}` : undefined}
          />
        )}
        {hasPs && (
          <MetricCell
            label="P/S"
            tip={METRIC_TIPS.ps_ttm}
            value={fmtMultiple(f.ps_ttm)}
          />
        )}
        {hasPeg && (
          <MetricCell
            label="PEG"
            tip={METRIC_TIPS.peg_ttm}
            value={fmtPeg(f.peg_ttm)}
            sub={f.forward_peg != null ? `Fwd ${fmtPeg(f.forward_peg)}` : undefined}
          />
        )}
      </div>
    </SectionBlock>
  );
}

function FinancialsQualityBlock({ f }: { f: StructuredNoteFinancials }) {
  const hasMargins =
    f.gross_margin_ttm != null ||
    f.operating_margin_ttm != null ||
    f.net_margin_ttm != null;
  const hasGrowth =
    f.revenue_growth_ttm != null ||
    f.eps_growth_ttm != null ||
    f.roe_ttm != null;

  if (!hasMargins && !hasGrowth) return null;

  return (
    <SectionBlock color="neutral" title="Financials & Quality">
      <div className="space-y-3">
        {hasMargins && (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 rounded-lg bg-secondary/50 px-4 py-3">
            {f.gross_margin_ttm != null && (
              <MetricCell
                label="Gross Margin"
                tip={METRIC_TIPS.gross_margin}
                value={fmtPct(f.gross_margin_ttm)}
                sub={f.gross_margin_5y != null ? `5Y avg ${fmtPct(f.gross_margin_5y)}` : undefined}
              />
            )}
            {f.operating_margin_ttm != null && (
              <MetricCell
                label="Op. Margin"
                tip={METRIC_TIPS.operating_margin}
                value={fmtPct(f.operating_margin_ttm)}
                sub={f.operating_margin_5y != null ? `5Y avg ${fmtPct(f.operating_margin_5y)}` : undefined}
              />
            )}
            {f.net_margin_ttm != null && (
              <MetricCell
                label="Net Margin"
                tip={METRIC_TIPS.net_margin}
                value={fmtPct(f.net_margin_ttm)}
                sub={f.net_margin_5y != null ? `5Y avg ${fmtPct(f.net_margin_5y)}` : undefined}
              />
            )}
          </div>
        )}
        {hasGrowth && (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 rounded-lg bg-secondary/50 px-4 py-3">
            {f.revenue_growth_ttm != null && (
              <MetricCell
                label="Rev Growth"
                tip={METRIC_TIPS.revenue_growth}
                value={fmtPctSigned(f.revenue_growth_ttm)}
                subColor={f.revenue_growth_ttm > 0 ? "text-success" : f.revenue_growth_ttm < 0 ? "text-destructive" : undefined}
              />
            )}
            {f.eps_growth_ttm != null && (
              <MetricCell
                label="EPS Growth"
                tip={METRIC_TIPS.eps_growth}
                value={fmtPctSigned(f.eps_growth_ttm)}
                subColor={f.eps_growth_ttm > 0 ? "text-success" : f.eps_growth_ttm < 0 ? "text-destructive" : undefined}
              />
            )}
            {f.roe_ttm != null && (
              <MetricCell
                label="ROE"
                tip={METRIC_TIPS.roe}
                value={fmtPct(f.roe_ttm)}
              />
            )}
          </div>
        )}
      </div>
    </SectionBlock>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

interface StructuredNoteViewProps {
  note: StructuredNote;
  symbol: string;
  companyName?: string | null;
  sector?: string | null;
  industry?: string | null;
}

export default function StructuredNoteView({
  note,
  symbol,
  companyName,
  sector,
  industry,
}: StructuredNoteViewProps) {
  const { stats } = note;
  const financials = note.financials ?? null;

  // ── Stat cells (only render non-null) ────────────────────────────────────
  const statCells: React.ReactNode[] = [];

  if (stats.market_cap != null) {
    statCells.push(
      <StatCell key="mc" label="Market Cap" value={fmtCap(stats.market_cap)} />,
    );
  }

  if (stats.eps_actual != null) {
    const beatSub =
      stats.eps_estimate != null && stats.eps_beat_pct != null
        ? `vs ${stats.eps_estimate.toFixed(2)}e \u00b7 ${stats.eps_beat_pct > 0 ? "+" : ""}${stats.eps_beat_pct.toFixed(1)}%`
        : stats.eps_estimate != null
          ? `vs ${stats.eps_estimate.toFixed(2)}e`
          : undefined;
    const beatColor =
      stats.eps_beat_pct != null
        ? stats.eps_beat_pct > 0
          ? "text-success"
          : stats.eps_beat_pct < 0
            ? "text-destructive"
            : undefined
        : undefined;
    statCells.push(
      <StatCell
        key="eps"
        label="EPS"
        value={`$${stats.eps_actual.toFixed(2)}`}
        sub={beatSub}
        subColor={beatColor}
      />,
    );
  }

  if (stats.revenue_actual != null) {
    const beatSub =
      stats.revenue_estimate != null && stats.revenue_beat_pct != null
        ? `vs ${fmtRevenue(stats.revenue_estimate)}e \u00b7 ${stats.revenue_beat_pct > 0 ? "+" : ""}${stats.revenue_beat_pct.toFixed(1)}%`
        : stats.revenue_estimate != null
          ? `vs ${fmtRevenue(stats.revenue_estimate)}e`
          : undefined;
    const beatColor =
      stats.revenue_beat_pct != null
        ? stats.revenue_beat_pct > 0
          ? "text-success"
          : stats.revenue_beat_pct < 0
            ? "text-destructive"
            : undefined
        : undefined;
    statCells.push(
      <StatCell
        key="rev"
        label="Revenue"
        value={fmtRevenue(stats.revenue_actual)}
        sub={beatSub}
        subColor={beatColor}
      />,
    );
  }

  if (stats.beat_count != null && stats.total_quarters != null) {
    statCells.push(
      <StatCell
        key="beats"
        label="Beat Streak"
        value={`${stats.beat_count}/${stats.total_quarters}`}
        sub="EPS beats"
      />,
    );
  }

  if (stats.latest_move_1d != null) {
    const pos = isPositive(stats.latest_move_1d);
    const neg = isNegative(stats.latest_move_1d);
    statCells.push(
      <StatCell
        key="move"
        label="Latest Move"
        value={
          <span className={cn(pos && "text-success", neg && "text-destructive")}>
            {stats.latest_move_1d}
          </span>
        }
        sub={`post-earnings 1d${stats.latest_outcome ? ` \u00b7 ${stats.latest_outcome}` : ""}`}
      />,
    );
  }

  return (
    <div className="px-6 py-5 space-y-6">
      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <div>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="font-display text-xl font-bold text-foreground leading-tight">
              {symbol}
            </h3>
            {companyName && (
              <p className="text-sm text-muted-foreground mt-0.5">
                {companyName}
              </p>
            )}
          </div>
          <RatingPill rating={note.rating} />
        </div>
        {(sector || industry || stats.market_cap != null) && (
          <p className="font-mono text-xs text-muted-foreground/70 mt-2">
            {[sector, industry, stats.market_cap != null ? fmtCap(stats.market_cap) : null]
              .filter(Boolean)
              .join(" \u00b7 ")}
          </p>
        )}
      </div>

      {/* ── Stat strip ────────────────────────────────────────────────────── */}
      {statCells.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4 rounded-lg bg-secondary/50 px-4 py-3">
          {statCells}
        </div>
      )}

      {/* ── Sections ──────────────────────────────────────────────────────── */}
      <div className="space-y-6">
        {note.what_they_do && (
          <SectionBlock color="about" title="What They Do">
            <p className="text-[13px] text-foreground/85 leading-[1.65]">
              {note.what_they_do}
            </p>
          </SectionBlock>
        )}

        {financials && <ValuationBlock f={financials} />}
        {financials && <FinancialsQualityBlock f={financials} />}

        {note.highlights.length > 0 && (
          <SectionBlock
            color="highlights"
            title="Recent Highlights"
            count={note.highlights.length}
          >
            <ItemList items={note.highlights} color="highlights" />
          </SectionBlock>
        )}

        {note.watch.length > 0 && (
          <SectionBlock color="watch" title="What to Watch" count={note.watch.length}>
            <ItemList items={note.watch} color="watch" />
          </SectionBlock>
        )}

        {note.risks.length > 0 && (
          <SectionBlock color="risks" title="Key Risks" count={note.risks.length}>
            <ItemList items={note.risks} color="risks" />
          </SectionBlock>
        )}
      </div>

      {/* ── Bottom Line ───────────────────────────────────────────────────── */}
      {note.bottom_line && (
        <div className="rounded-lg bg-cool/[0.05] border border-cool/15 px-4 py-3.5">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-cool mb-1.5">
            Bottom Line
          </p>
          <p className="text-[13px] text-foreground/85 leading-[1.65]">
            {note.bottom_line}
          </p>
        </div>
      )}
    </div>
  );
}
