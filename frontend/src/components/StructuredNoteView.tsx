"use client";

import { cn } from "@/lib/utils";
import type { BriefingInput, StructuredNote, StructuredNoteItem, StructuredNoteFinancials } from "@/lib/api";
import Tip from "@/components/Tip";
import LiveText from "@/components/LiveText";

// ── Helpers ──────────────────────────────────────────────────────────────────


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

function fmtPct(v: number | null): string | null {
  if (v == null) return null;
  return `${v.toFixed(1)}%`;
}

function fmtPctSigned(v: number | null): string | null {
  if (v == null) return null;
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}


// ── Color configs ────────────────────────────────────────────────────────────

const sectionColors = {
  about: {
    dot: "bg-cool",
    label: "text-cool",
    accent: "border-l-cool/30",
    bg: "bg-cool/[0.04]",
  },
  // green and red mean up and down alone (DESIGN.md): a highlight is not "up" and a risk is not "down"
  highlights: {
    dot: "bg-foreground",
    label: "text-foreground",
    accent: "border-l-foreground/30",
    bg: "bg-foreground/[0.03]",
  },
  watch: {
    dot: "bg-muted-foreground",
    label: "text-muted-foreground",
    accent: "border-l-muted-foreground/30",
    bg: "bg-muted-foreground/[0.04]",
  },
  risks: {
    dot: "bg-amber-500",
    label: "text-amber-500",
    accent: "border-l-amber-500/30",
    bg: "bg-amber-500/[0.04]",
  },
  neutral: {
    dot: "bg-muted-foreground/60",
    label: "text-muted-foreground",
    accent: "border-l-muted-foreground/20",
    bg: "bg-muted-foreground/[0.04]",
  },
  azure: {
    dot: "bg-cool",
    label: "text-cool",
    accent: "border-l-cool/30",
    bg: "bg-cool/[0.04]",
  },
  violet: {
    dot: "bg-violet",
    label: "text-violet",
    accent: "border-l-violet/30",
    bg: "bg-violet/[0.04]",
  },
} as const;

// ── Metric tooltips ──────────────────────────────────────────────────────────

const METRIC_TIPS: Record<string, string> = {
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

/** Big-number metric cell for editorial financial sections. */
function BigMetric({
  label,
  tip,
  value,
  sub,
  valueColor,
  isFirst,
}: {
  label: string;
  tip?: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  valueColor?: string;
  isFirst?: boolean;
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
    <div
      className={cn(
        "flex flex-col gap-0.5 py-1",
        !isFirst && "border-l border-border pl-4",
      )}
    >
      {labelEl}
      <span
        className={cn(
          "font-mono text-[26px] font-semibold leading-[0.95] tracking-tight",
          valueColor || "text-foreground",
        )}
      >
        {value}
      </span>
      {sub && (
        <span className="font-mono text-[10px] text-muted-foreground/70 mt-0.5">
          {sub}
        </span>
      )}
    </div>
  );
}

/** Renders a row of BigMetric cells in a responsive grid with hairline dividers. */
function MetricRow({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-y-3">
      {children}
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
  inputs,
}: {
  items: StructuredNoteItem[];
  color: keyof typeof sectionColors;
  inputs: BriefingInput[];
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
            <LiveText text={item.lead} inputs={inputs} />
          </p>
          <p className="text-[13px] text-foreground/80 leading-[1.65] mt-0.5">
            <LiveText text={item.detail} inputs={inputs} />
          </p>
        </div>
      ))}
    </div>
  );
}

// ── Financials blocks (Variant 3: editorial big-number) ─────────────────────

function FinancialsQualityBlock({ f }: { f: StructuredNoteFinancials }) {
  // Margins row
  const marginCells: React.ReactNode[] = [];
  if (f.gross_margin_ttm != null) {
    marginCells.push(
      <BigMetric
        key="gm"
        label="Gross Margin"
        tip={METRIC_TIPS.gross_margin}
        value={fmtPct(f.gross_margin_ttm)}
        sub={f.gross_margin_5y != null ? `5Y ${fmtPct(f.gross_margin_5y)}` : "TTM"}
        isFirst={marginCells.length === 0}
      />,
    );
  }
  if (f.operating_margin_ttm != null) {
    marginCells.push(
      <BigMetric
        key="om"
        label="Op. Margin"
        tip={METRIC_TIPS.operating_margin}
        value={fmtPct(f.operating_margin_ttm)}
        sub={f.operating_margin_5y != null ? `5Y ${fmtPct(f.operating_margin_5y)}` : "TTM"}
        isFirst={marginCells.length === 0}
      />,
    );
  }
  if (f.net_margin_ttm != null) {
    marginCells.push(
      <BigMetric
        key="nm"
        label="Net Margin"
        tip={METRIC_TIPS.net_margin}
        value={fmtPct(f.net_margin_ttm)}
        sub={f.net_margin_5y != null ? `5Y ${fmtPct(f.net_margin_5y)}` : "TTM"}
        isFirst={marginCells.length === 0}
      />,
    );
  }

  // Growth & Returns row
  const growthCells: React.ReactNode[] = [];
  if (f.revenue_growth_ttm != null) {
    growthCells.push(
      <BigMetric
        key="rg"
        label="Rev Growth"
        tip={METRIC_TIPS.revenue_growth}
        value={fmtPctSigned(f.revenue_growth_ttm)}
        sub="YoY"
        valueColor={f.revenue_growth_ttm >= 0 ? "text-success" : "text-destructive"}
        isFirst={growthCells.length === 0}
      />,
    );
  }
  if (f.eps_growth_ttm != null) {
    growthCells.push(
      <BigMetric
        key="eg"
        label="EPS Growth"
        tip={METRIC_TIPS.eps_growth}
        value={fmtPctSigned(f.eps_growth_ttm)}
        sub="YoY"
        valueColor={f.eps_growth_ttm >= 0 ? "text-success" : "text-destructive"}
        isFirst={growthCells.length === 0}
      />,
    );
  }
  if (f.roe_ttm != null) {
    growthCells.push(
      <BigMetric
        key="roe"
        label="ROE"
        tip={METRIC_TIPS.roe}
        value={fmtPct(f.roe_ttm)}
        sub="TTM"
        valueColor={f.roe_ttm >= 0 ? "text-success" : "text-destructive"}
        isFirst={growthCells.length === 0}
      />,
    );
  }

  if (marginCells.length === 0 && growthCells.length === 0) return null;

  return (
    <div className="rounded-[13px] border border-border px-5 py-4">
      <div className="flex items-center gap-2 mb-4">
        <span className="h-2 w-2 rounded-full bg-violet" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-violet">
          Financials & Quality
        </span>
      </div>
      <div className="space-y-4">
        {marginCells.length > 0 && (
          <div>
            <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/50 mb-2">
              Margins (TTM)
            </p>
            <MetricRow>{marginCells}</MetricRow>
          </div>
        )}
        {growthCells.length > 0 && (
          <div>
            <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/50 mb-2">
              Growth & Returns
            </p>
            <MetricRow>{growthCells}</MetricRow>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

interface StructuredNoteViewProps {
  note: StructuredNote;
  symbol: string;
  companyName?: string | null;
  sector?: string | null;
  industry?: string | null;
  liveInputs?: BriefingInput[];  // the API's live_inputs: the receipts behind the note's live figures (backend services/note_live)
}

export default function StructuredNoteView({
  note,
  symbol,
  companyName,
  sector,
  industry,
  liveInputs = [],
}: StructuredNoteViewProps) {
  const { stats } = note;
  const financials = note.financials ?? null;

  // ── Stat cells (only render non-null) ────────────────────────────────────
  const statCells: React.ReactNode[] = [];

  // The strip's EPS is the SEC diluted figure for the note's quarter (backend services/note_valuation.with_sec_eps), the figure its
  // text uses; no vendor actual, estimate, surprise, beat count or past move is shown (Block 2, 2026-10-20)
  if (stats.eps_sec != null) {
    statCells.push(<StatCell key="eps" label="EPS" value={`$${stats.eps_sec.toFixed(2)}`} />);
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
        </div>
        {(sector || industry) && (
          <p className="font-mono text-xs text-muted-foreground/70 mt-2">
            {[sector, industry]
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
              <LiveText text={note.what_they_do} inputs={liveInputs} />
            </p>
          </SectionBlock>
        )}

        {financials && <FinancialsQualityBlock f={financials} />}

        {note.highlights.length > 0 && (
          <SectionBlock
            color="highlights"
            title="Recent Highlights"
            count={note.highlights.length}
          >
            <ItemList items={note.highlights} color="highlights" inputs={liveInputs} />
          </SectionBlock>
        )}

        {note.watch.length > 0 && (
          <SectionBlock color="watch" title="What to Watch" count={note.watch.length}>
            <ItemList items={note.watch} color="watch" inputs={liveInputs} />
          </SectionBlock>
        )}

        {note.risks.length > 0 && (
          <SectionBlock color="risks" title="Key Risks" count={note.risks.length}>
            <ItemList items={note.risks} color="risks" inputs={liveInputs} />
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
            <LiveText text={note.bottom_line} inputs={liveInputs} />
          </p>
        </div>
      )}
    </div>
  );
}
