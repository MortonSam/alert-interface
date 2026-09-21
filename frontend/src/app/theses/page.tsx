"use client";

import { volRegime } from "@/lib/encodings/volRegime";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { fmtTimestamp, markBasisLabel, optionsAsOfLabel } from "@/lib/marks";
import { fmtPnlPct } from "@/lib/pnl";
import {
  api,
  type Thesis,
  type ThesisContextItem,
  type ThesisMarkRead,
  type ThesisStockMarkRead,
  type ThesisResolve,
  type SelfGrade,
} from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Returns true when US equity markets are plausibly open.
 * Heuristic only — no holiday calendar. Uses America/New_York via the browser's
 * Intl API so DST is handled automatically. Mon-Fri 09:30-16:00 ET.
 */
function isMarketHours(): boolean {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date());
  const get = (type: string) => parts.find(p => p.type === type)?.value ?? "";
  const weekday = get("weekday");
  const mins = parseInt(get("hour"), 10) * 60 + parseInt(get("minute"), 10);
  return !["Sat", "Sun"].includes(weekday) && mins >= 9 * 60 + 30 && mins < 16 * 60;
}

function fmtPrice(v: string | null | undefined): string {
  if (v == null) return "n/a";
  const n = parseFloat(v);
  return isNaN(n) ? "n/a" : `$${n.toFixed(2)}`;
}

function fmtDate(v: string): string {
  const [y, m, d] = v.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });
}

function fmtDateShort(v: string): string {
  const [y, m, d] = v.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function pctChange(entry: string | null, resolution: string | null): string {
  if (!entry || !resolution) return "";
  const e = parseFloat(entry);
  const r = parseFloat(resolution);
  if (!e) return "";
  const pct = ((r - e) / e) * 100;
  return (pct >= 0 ? "+" : "") + pct.toFixed(1) + "%";
}

function fmtPnl(dollars: number | null, pct: number | null): { str: string; color: string } {
  if (dollars == null) return { str: "n/a", color: "text-muted-foreground" };
  const sign = dollars >= 0 ? "+" : "-";
  const pctStr = pct != null ? ` (${fmtPnlPct(pct)})` : "";
  const absStr = `${sign}$${Math.abs(dollars).toFixed(0)}${pctStr}`;
  const color =
    dollars > 0 ? "text-success" :
    dollars < 0 ? "text-destructive" :
    "text-foreground";
  return { str: absStr, color };
}

function fmtOptionLeg(thesis: Thesis): string | null {
  if (!thesis.option_type || !thesis.strike) return null;
  const s1 = parseFloat(thesis.strike);
  const exp = thesis.option_expiration ? fmtDateShort(thesis.option_expiration) : "n/a";
  if (thesis.strike2) {
    const s2 = parseFloat(thesis.strike2);
    const name = thesis.option_type === "call" ? "Bull call spread" : "Bear put spread";
    return `${name} $${s1.toFixed(0)}/$${s2.toFixed(0)} · ${exp}`;
  }
  const name = thesis.option_type === "call" ? "Long call" : "Long put";
  return `${name} $${s1.toFixed(0)} · ${exp}`;
}

const DIRECTION_COLOR: Record<string, string> = {
  bullish: "text-success",
  bearish: "text-destructive",
  neutral: "text-muted-foreground",
};

const GRADE_LABEL: Record<SelfGrade, string> = {
  right: "Right",
  right_for_wrong_reasons: "Right (wrong reasons)",
  wrong: "Wrong",
};

const GRADE_COLOR: Record<SelfGrade, string> = {
  right: "text-success",
  right_for_wrong_reasons: "text-amber-500",
  wrong: "text-destructive",
};

function ConvictionDots({ n }: { n: number }) {
  return (
    <span className="flex gap-0.5 items-center">
      {Array.from({ length: 5 }).map((_, i) => (
        <span
          key={i}
          className={`inline-block w-2 h-2 rounded-full ${i < n ? "bg-cool" : "bg-muted"}`}
        />
      ))}
    </span>
  );
}

// ── Option P&L section ────────────────────────────────────────────────────────

function OptionPnlSection({
  thesis,
  mark,
  refreshing,
}: {
  thesis: Thesis;
  mark?: ThesisMarkRead | "loading" | "error";
  refreshing?: boolean;
}) {
  const legDesc = fmtOptionLeg(thesis);
  if (!legDesc) return null;

  let pnlDollars: number | null = null;
  let pnlPct: number | null = null;
  let markLabel: string | null = null;
  let markNote: string | null = null;
  let isLoading = false;
  let isError = false;
  let isNoData = false;

  let asOf: string | null = null;

  if (thesis.status === "resolved") {
    pnlDollars = thesis.option_pnl_dollars ? parseFloat(thesis.option_pnl_dollars) : null;
    pnlPct = thesis.option_pnl_pct ? parseFloat(thesis.option_pnl_pct) : null;
    markLabel = "at resolution";
  } else if (mark === "loading") {
    isLoading = true;
  } else if (mark === "error") {
    isError = true;
  } else if (mark) {
    if (mark.mark_basis === "no_option_leg") {
      isNoData = true;
    } else {
      pnlDollars = mark.pnl_dollars;
      pnlPct = mark.pnl_pct;
      markLabel = [markBasisLabel(mark.mark_basis), optionsAsOfLabel(mark)].filter(Boolean).join(" · ");
      markNote = mark.mark_note;
      asOf = mark.as_of; // when the mark was computed (ISO); the options date is in markLabel
    }
  }

  if (isNoData) return null;

  const { str: pnlStr, color: pnlColor } = fmtPnl(pnlDollars, pnlPct);

  return (
    <div className="mt-2 mb-1">
      <div className="text-xs text-muted-foreground mb-0.5">{legDesc}</div>
      {isLoading ? (
        <div className="h-6 bg-muted rounded w-28 animate-pulse" />
      ) : isError ? (
        <span className="text-xs text-muted-foreground italic">Mark unavailable</span>
      ) : (
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className={`text-xl font-bold font-mono tabular-nums leading-tight transition-opacity ${pnlColor} ${refreshing ? "opacity-50" : ""}`}>
            {pnlStr}
          </span>
          {markLabel && (
            <span className="text-xs text-muted-foreground">{markLabel}</span>
          )}
          {asOf && (
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              checked <span className="font-mono">{fmtTimestamp(asOf) ?? "time unknown"}</span>
              {refreshing && (
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-muted-foreground/60 animate-pulse" />
              )}
            </span>
          )}
        </div>
      )}
      {markNote && !isError && (
        <p className="text-xs text-muted-foreground mt-0.5 italic">{markNote}</p>
      )}
    </div>
  );
}

// ── Stock price mark (for theses with no option leg) ──────────────────────────

const VERDICT_COLOR: Record<string, string> = {
  on_track:   "text-success",
  reversed:   "text-destructive",
  target_hit: "text-success font-semibold",
};
const VERDICT_LABEL: Record<string, string> = {
  on_track:   "On track",
  reversed:   "Reversed",
  target_hit: "Target hit",
};

function StockPriceMark({
  thesis,
  mark,
  refreshing,
}: {
  thesis: Thesis;
  mark?: ThesisStockMarkRead | "loading" | "error";
  refreshing?: boolean;
}) {
  // Only renders for open stock-only theses — option theses use OptionPnlSection.
  if (thesis.option_type) return null;
  if (thesis.status === "resolved") return null;

  if (!mark || mark === "error") return null;

  if (mark === "loading") {
    return (
      <div className="mt-2 mb-1">
        <div className="h-5 bg-muted rounded w-44 animate-pulse" />
      </div>
    );
  }

  const { verdict, pct_from_entry, pct_to_target, current_price, as_of } = mark;

  const pctSign  = pct_from_entry != null && pct_from_entry >= 0 ? "+" : "";
  const pctColor =
    pct_from_entry == null ? "text-muted-foreground" :
    pct_from_entry > 0     ? "text-success" :
    pct_from_entry < 0     ? "text-destructive" :
                             "text-foreground";

  // Clamp display to 0–100% so "−5% to target" doesn't mislead
  const pctToDisplay =
    pct_to_target != null
      ? Math.max(0, Math.min(100, pct_to_target)).toFixed(0)
      : null;

  return (
    <div className="mt-2 mb-1 space-y-0.5">
      {/* Headline: current price + % from entry */}
      <div className="flex items-center gap-2 flex-wrap text-sm">
        {current_price != null && (
          <span className="font-mono font-medium tabular-nums text-foreground">${current_price.toFixed(2)}</span>
        )}
        {pct_from_entry != null && (
          <span className={`font-mono tabular-nums ${pctColor}`}>
            {pctSign}{pct_from_entry.toFixed(2)}% from entry
          </span>
        )}
        {pctToDisplay != null && (
          <span className="font-mono tabular-nums text-muted-foreground text-xs">
            · {pctToDisplay}% of the way to target
          </span>
        )}
      </div>
      {/* Verdict + as-of timestamp */}
      <div className="flex items-center gap-2 text-xs">
        {verdict && (
          <span className={VERDICT_COLOR[verdict] ?? "text-muted-foreground"}>
            {VERDICT_LABEL[verdict] ?? verdict}
          </span>
        )}
        <span className="text-muted-foreground flex items-center gap-1">
          as of <span className="font-mono">{fmtTimestamp(as_of) ?? "time unknown"}</span>
          {refreshing && (
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-muted-foreground/60 animate-pulse" />
          )}
        </span>
      </div>
    </div>
  );
}

// ── Resolve form ──────────────────────────────────────────────────────────────

function ResolveForm({
  thesis,
  onResolved,
  onCancel,
}: {
  thesis: Thesis;
  onResolved: (t: Thesis) => void;
  onCancel: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<ThesisResolve>({ reflection: "", self_grade: "right" });
  const [priceOverride, setPriceOverride] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload: ThesisResolve = {
        ...form,
        ...(priceOverride ? { price_override: parseFloat(priceOverride) } : {}),
      };
      const updated = await api.theses.resolve(thesis.id, payload);
      onResolved(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resolve");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 space-y-3 border-t pt-3">
      <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide">Resolve Thesis</p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Self-grade</label>
          <select
            className="w-full rounded-md border bg-background px-2 py-1.5 text-sm"
            value={form.self_grade}
            onChange={e => setForm(f => ({ ...f, self_grade: e.target.value as SelfGrade }))}
          >
            <option value="right">Right</option>
            <option value="right_for_wrong_reasons">Right (wrong reasons)</option>
            <option value="wrong">Wrong</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Price override (optional)</label>
          <input
            type="number" step="0.01" min="0"
            className="w-full rounded-md border bg-background px-2 py-1.5 text-sm"
            placeholder="Uses the latest quote if blank"
            value={priceOverride}
            onChange={e => setPriceOverride(e.target.value)}
          />
        </div>
      </div>
      <div>
        <label className="text-xs text-muted-foreground mb-1 block">Reflection</label>
        <textarea
          className="w-full rounded-md border bg-background px-3 py-1.5 text-sm resize-none"
          rows={2}
          placeholder="What happened? What did you get right or wrong?"
          value={form.reflection}
          onChange={e => setForm(f => ({ ...f, reflection: e.target.value }))}
          required
        />
      </div>
      {thesis.option_type && (
        <p className="text-xs text-muted-foreground">Option P&L is computed from the stored options data at resolution, or at intrinsic value once expired.</p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-sm font-medium hover:opacity-90 disabled:opacity-50"
        >
          {saving ? "Resolving…" : "Resolve"}
        </button>
        <button type="button" onClick={onCancel} className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent">
          Cancel
        </button>
      </div>
    </form>
  );
}

// ── Thesis card ───────────────────────────────────────────────────────────────

function ThesisCard({
  thesis,
  mark,
  stockMark,
  refreshing,
  ctx,
  onResolved,
  onDeleted,
}: {
  thesis: Thesis;
  mark?: ThesisMarkRead | "loading" | "error";
  stockMark?: ThesisStockMarkRead | "loading" | "error";
  refreshing?: boolean;
  ctx?: ThesisContextItem;
  onResolved: (t: Thesis) => void;
  onDeleted: (id: string) => void;
}) {
  const [resolving, setResolving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const [reflectionOpen, setReflectionOpen] = useState(false);

  const isOpen      = thesis.status === "open" || thesis.status === "needs_manual_resolution";
  const needsManual = thesis.status === "needs_manual_resolution";
  const isResolved  = thesis.status === "resolved";

  async function handleDelete() {
    if (!confirm(`Delete thesis for ${thesis.ticker_symbol}?`)) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.theses.delete(thesis.id);
      onDeleted(thesis.id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      // 404 means it's already gone — remove from UI anyway
      if (msg.includes("404")) {
        onDeleted(thesis.id);
      } else {
        setDeleting(false);
        setDeleteError(msg);
      }
    }
  }

  return (
    <div className={`border-b border-border/40 pb-4 space-y-2 ${deleting ? "opacity-40" : ""}`}>
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <Link href={`/tickers/${thesis.ticker_symbol}`} className="font-semibold hover:underline">
            {thesis.ticker_symbol ?? "n/a"}
          </Link>
          <span className={`text-sm font-medium capitalize ${DIRECTION_COLOR[thesis.direction]}`}>
            {thesis.direction}
          </span>
          <ConvictionDots n={thesis.conviction} />
          {thesis.is_due && isOpen && (
            <span className="text-xs bg-amber-500/10 text-amber-500 px-1.5 py-0.5 rounded">
              Due
            </span>
          )}
          {needsManual && (
            <span className="text-xs bg-primary/10 text-primary px-1.5 py-0.5 rounded">
              Needs manual resolution
            </span>
          )}
          {thesis.from_ai_draft && (
            <span className="text-xs bg-orange-500/10 text-orange-600 dark:text-orange-400 border border-orange-500/30 px-1.5 py-0.5 rounded">
              Ivy
            </span>
          )}
        </div>
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="text-xs text-muted-foreground hover:text-destructive shrink-0"
        >
          Delete
        </button>
      </div>

      {deleteError && (
        <p className="text-xs text-destructive">Delete failed: {deleteError}</p>
      )}

      {/* ── Context chips (open theses only) ──────────────────────────── */}
      {isOpen && ctx && (ctx.earnings_proximity || ctx.vol_regime || ctx.insight) && (
        <div className="flex items-center gap-1.5 flex-wrap">
          {ctx.earnings_proximity && (
            <span className="inline-flex items-center rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 px-2 py-0.5 text-[10px] font-semibold tracking-wide">
              {ctx.earnings_proximity}
            </span>
          )}
          {volRegime(ctx.vol_regime) && ctx.vol_regime !== "iv_fair" && (
            <span
              title={volRegime(ctx.vol_regime)!.rule}
              className={`inline-flex items-center rounded-full ${volRegime(ctx.vol_regime)!.className} px-2 py-0.5 text-[10px] font-semibold tracking-wide`}
            >
              {volRegime(ctx.vol_regime)!.label}
            </span>
          )}
          {ctx.insight && (
            <span className="text-[11px] text-muted-foreground/70 leading-snug">
              {ctx.insight}
            </span>
          )}
        </div>
      )}

      {/* ── Option P&L headline (option theses only) ───────────────────── */}
      <OptionPnlSection thesis={thesis} mark={mark} refreshing={refreshing} />

      {/* ── Stock price mark (stock-only theses, open) ─────────────────── */}
      <StockPriceMark thesis={thesis} mark={stockMark} refreshing={refreshing} />

      {/* ── Compact fact row ───────────────────────────────────────────── */}
      <div className="flex items-center gap-3 text-sm flex-wrap text-muted-foreground">
        <span>Entry: <span className="font-mono tabular-nums text-foreground font-medium">{fmtPrice(thesis.entry_price)}</span></span>
        {thesis.price_target && (
          <span>→ Target: <span className="font-mono tabular-nums text-foreground font-medium">{fmtPrice(thesis.price_target)}</span></span>
        )}
        <span>By: <span className="font-mono tabular-nums text-foreground">{fmtDate(thesis.target_date)}</span></span>
        {thesis.catalyst && (
          <span className="text-muted-foreground">· {thesis.catalyst}</span>
        )}
      </div>

      {/* ── Option entry details (when tracked) ───────────────────────── */}
      {thesis.entry_premium && (
        <div className="flex items-center gap-3 flex-wrap">
          <p className="text-xs text-muted-foreground">
            Option entry: <span className="font-mono tabular-nums text-foreground">
              {thesis.strike2 && thesis.entry_premium2
                ? `$${Math.abs(parseFloat(thesis.entry_premium) - parseFloat(thesis.entry_premium2)).toFixed(2)} net debit`
                : `$${parseFloat(thesis.entry_premium).toFixed(2)} mid`}
            </span>
            {thesis.contracts > 1 && ` · ${thesis.contracts} contracts`}
          </p>
          <Link
            href={`/theses/${thesis.id}`}
            className="text-xs text-cool hover:text-cool/80 transition-colors"
          >
            Simulate →
          </Link>
        </div>
      )}

      {/* ── Collapsible reasoning ──────────────────────────────────────── */}
      {thesis.reasoning && (
        <div>
          <button
            type="button"
            onClick={() => setReasoningOpen(o => !o)}
            className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
          >
            {reasoningOpen ? "▾" : "▸"} Reasoning
          </button>
          {reasoningOpen && (
            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">{thesis.reasoning}</p>
          )}
        </div>
      )}

      {/* ── Resolution outcome ─────────────────────────────────────────── */}
      {isResolved && (
        <div className="rounded-md bg-muted/40 px-3 py-2 space-y-1.5">
          {/* Stock outcome row */}
          <div className="flex items-center gap-3 flex-wrap text-sm">
            <span className="text-muted-foreground">
              Resolved:{" "}
              <span className="text-foreground font-medium">{fmtPrice(thesis.price_at_resolution)}</span>
              {" "}
              <span className={
                thesis.direction === "bullish"
                  ? parseFloat(thesis.price_at_resolution ?? "0") >= parseFloat(thesis.entry_price ?? "0")
                    ? "text-success" : "text-destructive"
                  : thesis.direction === "bearish"
                  ? parseFloat(thesis.price_at_resolution ?? "0") <= parseFloat(thesis.entry_price ?? "0")
                    ? "text-success" : "text-destructive"
                  : ""
              }>
                ({pctChange(thesis.entry_price, thesis.price_at_resolution)})
              </span>
            </span>
            {thesis.direction_correct != null && (
              <span>
                Direction:{" "}
                <span className={thesis.direction_correct ? "text-success" : "text-destructive"}>
                  {thesis.direction_correct ? "✓" : "✗"}
                </span>
              </span>
            )}
            {thesis.target_reached != null && (
              <span>
                Target:{" "}
                <span className={thesis.target_reached ? "text-success" : "text-destructive"}>
                  {thesis.target_reached ? "✓" : "✗"}
                </span>
              </span>
            )}
            {thesis.self_grade && (
              <span className={`font-medium ${GRADE_COLOR[thesis.self_grade]}`}>
                {GRADE_LABEL[thesis.self_grade]}
              </span>
            )}
          </div>

          {/* AI verdict row (if option P&L stored) */}
          {thesis.option_pnl_dollars != null && (
            <div className="text-xs text-muted-foreground">
              Trade:{" "}
              <span className={
                parseFloat(thesis.option_pnl_dollars) >= 0
                  ? "text-success font-medium"
                  : "text-destructive font-medium"
              }>
                {fmtPnl(parseFloat(thesis.option_pnl_dollars), thesis.option_pnl_pct ? parseFloat(thesis.option_pnl_pct) : null).str}
              </span>
            </div>
          )}

          {/* Collapsible reflection */}
          {thesis.reflection && (
            <div>
              <button
                type="button"
                onClick={() => setReflectionOpen(o => !o)}
                className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
              >
                {reflectionOpen ? "▾" : "▸"} Reflection
              </button>
              {reflectionOpen && (
                <p className="text-sm text-muted-foreground mt-1 italic leading-relaxed">&ldquo;{thesis.reflection}&rdquo;</p>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Resolve button / form ──────────────────────────────────────── */}
      {isOpen && (
        resolving ? (
          <ResolveForm
            thesis={thesis}
            onResolved={t => { onResolved(t); setResolving(false); }}
            onCancel={() => setResolving(false)}
          />
        ) : (
          thesis.is_due && (
            <button
              onClick={() => setResolving(true)}
              className="text-sm text-cool hover:text-cool/80 transition-colors"
            >
              Resolve thesis
            </button>
          )
        )
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 60_000; // 60s — aligns with the 45s chain cache TTL; most polls are cache hits

export default function ThesesPage() {
  const [theses, setTheses] = useState<Thesis[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<"all" | "open" | "resolved">("all");
  const [marks, setMarks] = useState<Record<string, ThesisMarkRead | "loading" | "error">>({});
  const [stockMarks, setStockMarks] = useState<Record<string, ThesisStockMarkRead | "loading" | "error">>({});
  const [context, setContext] = useState<Record<string, ThesisContextItem>>({});
  const [refreshing, setRefreshing] = useState<Set<string>>(new Set());
  const [stockRefreshing, setStockRefreshing] = useState<Set<string>>(new Set());
  const initialized = useRef(false);
  const markRequested = useRef<Set<string>>(new Set());
  const stockMarkRequested = useRef<Set<string>>(new Set());
  // Stable ref so the polling closure always reads the current thesis list
  const thesesRef = useRef<Thesis[]>([]);
  useEffect(() => { thesesRef.current = theses; }, [theses]);

  // Initial load
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    api.theses.list().then(data => {
      setTheses(data);
      setLoading(false);
      // Fetch context for open thesis symbols
      const openSymbols = [...new Set(
        data
          .filter(t => t.status === "open" || t.status === "needs_manual_resolution")
          .map(t => t.ticker_symbol)
          .filter(Boolean) as string[]
      )];
      if (openSymbols.length > 0) {
        api.theses.context(openSymbols).then(setContext).catch(() => {});
      }
    }).catch(() => setLoading(false));
  }, []);

  // Live re-mark polling for open positions during market hours.
  // Runs every 60s; pauses when the tab is hidden; resumes immediately on focus.
  useEffect(() => {
    const pollAll = () => {
      // Only poll during US market hours (America/New_York, Mon-Fri 09:30-16:00 ET).
      // Outside hours the last mark remains visible with its as_of timestamp, which is honest.
      if (!isMarketHours()) return;
      if (document.hidden) return;

      const targets = thesesRef.current.filter(
        t => (t.status === "open" || t.status === "needs_manual_resolution") && t.option_type
      );
      if (targets.length === 0) return;

      // All open positions fire simultaneously — a single batch per interval.
      // Same-symbol+expiration hits share the 45s chain cache, so only the first
      // request in a batch actually calls yfinance; the rest are in-process cache hits.
      const ids = targets.map(t => t.id);
      setRefreshing(new Set(ids));

      Promise.all(
        ids.map(id =>
          api.theses.mark(id)
            .then(data => ({ id, data, ok: true as const }))
            .catch(() => ({ id, data: null, ok: false as const }))
        )
      ).then(results => {
        setMarks(prev => {
          const next = { ...prev };
          for (const r of results) {
            if (r.ok && r.data) next[r.id] = r.data;
            // On transient error: keep the previous value rather than flipping to "error"
          }
          return next;
        });
        setRefreshing(new Set());
      });
    };

    pollAll(); // fire immediately on mount; don't wait up to 60s for the first tick
    const interval = setInterval(pollAll, POLL_INTERVAL_MS);

    // Pause when tab hides; poll immediately when it comes back into focus
    const onVisibilityChange = () => {
      if (!document.hidden) pollAll();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []); // intentionally stable — reads current theses via thesesRef

  // Progressive mark loading for open theses with option legs
  useEffect(() => {
    const openWithOptions = theses.filter(
      t => (t.status === "open" || t.status === "needs_manual_resolution") && t.option_type
    );
    const newOnes = openWithOptions.filter(t => !markRequested.current.has(t.id));
    if (newOnes.length === 0) return;

    for (const t of newOnes) {
      markRequested.current.add(t.id);
      setMarks(prev => ({ ...prev, [t.id]: "loading" }));
      api.theses.mark(t.id)
        .then(data => setMarks(prev => ({ ...prev, [t.id]: data })))
        .catch(() => setMarks(prev => ({ ...prev, [t.id]: "error" })));
    }
  }, [theses]);

  // Progressive mark loading for open stock-only theses (separate from option path)
  useEffect(() => {
    const openStockTheses = theses.filter(
      t => (t.status === "open" || t.status === "needs_manual_resolution") && !t.option_type
    );
    const newOnes = openStockTheses.filter(t => !stockMarkRequested.current.has(t.id));
    if (newOnes.length === 0) return;

    for (const t of newOnes) {
      stockMarkRequested.current.add(t.id);
      setStockMarks(prev => ({ ...prev, [t.id]: "loading" }));
      api.theses.stockMark(t.id)
        .then(data => {
          setStockMarks(prev => ({ ...prev, [t.id]: data }));
          // Auto-resolution happened server-side — refresh thesis list so the
          // card transitions from open to resolved without a page reload.
          if (data.auto_resolved) {
            api.theses.list().then(fresh => setTheses(fresh)).catch(() => null);
          }
        })
        .catch(() => setStockMarks(prev => ({ ...prev, [t.id]: "error" })));
    }
  }, [theses]);

  // Live re-mark polling for open stock-only theses during market hours.
  // Mirrors the option polling effect but is fully independent — touches only
  // stockMarks / stockRefreshing, never the option mark state.
  useEffect(() => {
    const pollStockAll = () => {
      if (!isMarketHours()) return;
      if (document.hidden) return;

      const targets = thesesRef.current.filter(
        t => (t.status === "open" || t.status === "needs_manual_resolution") && !t.option_type
      );
      if (targets.length === 0) return;

      const ids = targets.map(t => t.id);
      setStockRefreshing(new Set(ids));

      Promise.all(
        ids.map(id =>
          api.theses.stockMark(id)
            .then(data => ({ id, data, ok: true as const }))
            .catch(() => ({ id, data: null, ok: false as const }))
        )
      ).then(results => {
        let anyAutoResolved = false;
        setStockMarks(prev => {
          const next = { ...prev };
          for (const r of results) {
            if (r.ok && r.data) {
              next[r.id] = r.data;
              if (r.data.auto_resolved) anyAutoResolved = true;
            }
            // On transient error: keep the previous value (same policy as option polling)
          }
          return next;
        });
        setStockRefreshing(new Set());
        if (anyAutoResolved) {
          api.theses.list().then(fresh => setTheses(fresh)).catch(() => null);
        }
      });
    };

    pollStockAll();
    const interval = setInterval(pollStockAll, POLL_INTERVAL_MS);
    const onVisibilityChange = () => { if (!document.hidden) pollStockAll(); };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []); // intentionally stable — reads current theses via thesesRef

  function handleResolved(updated: Thesis) {
    setTheses(prev => prev.map(t => t.id === updated.id ? updated : t));
    // Resolved cards use stored outcome — remove from both live-mark dicts
    setMarks(prev => { const next = { ...prev }; delete next[updated.id]; return next; });
    setStockMarks(prev => { const next = { ...prev }; delete next[updated.id]; return next; });
  }

  function handleDeleted(id: string) {
    setTheses(prev => prev.filter(t => t.id !== id));
    setMarks(prev => { const next = { ...prev }; delete next[id]; return next; });
    setStockMarks(prev => { const next = { ...prev }; delete next[id]; return next; });
  }

  const filtered = theses.filter(t => {
    if (statusFilter === "open") return t.status === "open" || t.status === "needs_manual_resolution";
    if (statusFilter === "resolved") return t.status === "resolved";
    return true;
  });

  const openCount = theses.filter(t => t.status === "open" || t.status === "needs_manual_resolution").length;
  const dueCount  = theses.filter(t => t.is_due && (t.status === "open" || t.status === "needs_manual_resolution")).length;

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-start justify-between mb-6">
          <div>
            <h1 className="text-2xl font-display font-bold tracking-tight">My Trades</h1>
            <p className="text-muted-foreground text-sm mt-0.5">
              {openCount} open{dueCount > 0 ? ` · ${dueCount} due for resolution` : ""}
            </p>
          </div>
          <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
            ← Home
          </Link>
        </div>

        <Link
          href="/build"
          className="inline-flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          + Build a Trade
        </Link>

        {/* Filter tabs */}
        <div className="flex gap-1 mt-6 mb-4">
          {(["all", "open", "resolved"] as const).map(f => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={`px-3 py-1 rounded-full text-sm capitalize transition-colors ${
                statusFilter === f
                  ? "bg-secondary text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {f}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="border-b border-border/40 pb-4 animate-pulse space-y-2">
                <div className="h-4 bg-muted rounded w-32" />
                <div className="h-3 bg-muted rounded w-48" />
                <div className="h-3 bg-muted rounded w-64" />
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-muted-foreground text-sm py-8 text-center">
            {statusFilter === "all" ? "No theses yet. Start one with Build a Trade." : `No ${statusFilter} theses.`}
          </p>
        ) : (
          <div className="space-y-3">
            {filtered.map(thesis => (
              <ThesisCard
                key={thesis.id}
                thesis={thesis}
                mark={thesis.status !== "resolved" ? marks[thesis.id] : undefined}
                stockMark={thesis.status !== "resolved" ? stockMarks[thesis.id] : undefined}
                refreshing={refreshing.has(thesis.id) || stockRefreshing.has(thesis.id)}
                ctx={thesis.ticker_symbol ? context[thesis.ticker_symbol] : undefined}
                onResolved={handleResolved}
                onDeleted={handleDeleted}
              />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
