import { cn } from "@/lib/utils";
import type { StructuredNote, StructuredNoteItem } from "@/lib/api";

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
} as const;

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
      <span className="text-[8px]">●</span>
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
        ? `vs ${stats.eps_estimate.toFixed(2)}e · ${stats.eps_beat_pct > 0 ? "+" : ""}${stats.eps_beat_pct.toFixed(1)}%`
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
        ? `vs ${fmtRevenue(stats.revenue_estimate)}e · ${stats.revenue_beat_pct > 0 ? "+" : ""}${stats.revenue_beat_pct.toFixed(1)}%`
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
        sub={`post-earnings 1d${stats.latest_outcome ? ` · ${stats.latest_outcome}` : ""}`}
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
              .join(" · ")}
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
