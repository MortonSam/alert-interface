"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  type Thesis,
  type ThesisCreate,
  type ThesisDraftRead,
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

/** Format an ISO timestamp as "HH:MM:SS" (local time) for same-day, or "EEE HH:MM" across days. */
function fmtAsOf(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    const now = new Date();
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth()    === now.getMonth()    &&
      d.getDate()     === now.getDate();
    if (sameDay) {
      return d.toLocaleTimeString("en-US", {
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
      });
    }
    return d.toLocaleString("en-US", {
      weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false,
    });
  } catch {
    return isoStr;
  }
}

function fmtPrice(v: string | null | undefined): string {
  if (v == null) return "—";
  const n = parseFloat(v);
  return isNaN(n) ? "—" : `$${n.toFixed(2)}`;
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
  if (dollars == null) return { str: "—", color: "text-muted-foreground" };
  const sign = dollars >= 0 ? "+" : "";
  const pctStr = pct != null ? ` (${pct >= 0 ? "+" : ""}${(pct * 100).toFixed(1)}%)` : "";
  const absStr = `${sign}$${Math.abs(dollars).toFixed(0)}${pctStr}`;
  const color =
    dollars > 0 ? "text-emerald-600 dark:text-emerald-400" :
    dollars < 0 ? "text-red-500 dark:text-red-400" :
    "text-foreground";
  return { str: absStr, color };
}

function fmtOptionLeg(thesis: Thesis): string | null {
  if (!thesis.option_type || !thesis.strike) return null;
  const s1 = parseFloat(thesis.strike);
  const exp = thesis.option_expiration ? fmtDateShort(thesis.option_expiration) : "—";
  if (thesis.strike2) {
    const s2 = parseFloat(thesis.strike2);
    const name = thesis.option_type === "call" ? "Bull call spread" : "Bear put spread";
    return `${name} $${s1.toFixed(0)}/$${s2.toFixed(0)} · ${exp}`;
  }
  const name = thesis.option_type === "call" ? "Long call" : "Long put";
  return `${name} $${s1.toFixed(0)} · ${exp}`;
}

const DIRECTION_COLOR: Record<string, string> = {
  bullish: "text-emerald-600 dark:text-emerald-400",
  bearish: "text-red-500 dark:text-red-400",
  neutral: "text-slate-500",
};

const GRADE_LABEL: Record<SelfGrade, string> = {
  right: "Right",
  right_for_wrong_reasons: "Right (wrong reasons)",
  wrong: "Wrong",
};

const GRADE_COLOR: Record<SelfGrade, string> = {
  right: "text-emerald-600 dark:text-emerald-400",
  right_for_wrong_reasons: "text-amber-500",
  wrong: "text-red-500 dark:text-red-400",
};

function ConvictionDots({ n }: { n: number }) {
  return (
    <span className="flex gap-0.5 items-center">
      {Array.from({ length: 5 }).map((_, i) => (
        <span
          key={i}
          className={`inline-block w-2 h-2 rounded-full ${i < n ? "bg-blue-500" : "bg-muted"}`}
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
      markLabel = mark.is_expired ? "intrinsic" : mark.mark_basis === "live_chain" ? "live" : null;
      markNote = mark.mark_note;
      asOf = mark.as_of; // actual chain fetch time, not request time
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
          <span className={`text-xl font-bold tabular-nums leading-tight transition-opacity ${pnlColor} ${refreshing ? "opacity-50" : ""}`}>
            {pnlStr}
          </span>
          {markLabel && (
            <span className="text-xs text-muted-foreground">{markLabel}</span>
          )}
          {asOf && (
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              as of {fmtAsOf(asOf)}
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
  on_track:   "text-emerald-600 dark:text-emerald-400",
  reversed:   "text-red-500 dark:text-red-400",
  target_hit: "text-emerald-700 dark:text-emerald-300 font-semibold",
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
    pct_from_entry == null       ? "text-muted-foreground" :
    pct_from_entry > 0           ? "text-emerald-600 dark:text-emerald-400" :
    pct_from_entry < 0           ? "text-red-500 dark:text-red-400" :
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
          <span className="font-medium text-foreground">${current_price.toFixed(2)}</span>
        )}
        {pct_from_entry != null && (
          <span className={pctColor}>
            {pctSign}{pct_from_entry.toFixed(2)}% from entry
          </span>
        )}
        {pctToDisplay != null && (
          <span className="text-muted-foreground text-xs">
            · {pctToDisplay}% to target
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
          as of {fmtAsOf(as_of)}
          {refreshing && (
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-muted-foreground/60 animate-pulse" />
          )}
        </span>
      </div>
    </div>
  );
}

// ── Draft panel ───────────────────────────────────────────────────────────────

interface OptionLegDraft {
  option_type: "call" | "put";
  strike: number | null;
  strike2: number | null;
  option_expiration: string | null;
  spread_type: string | null;
}

function DraftPanel({
  draft,
  onAccept,
}: {
  draft: ThesisDraftRead;
  onAccept: (
    target: number | null,
    reasoning: string | null,
    optionLeg: OptionLegDraft | null
  ) => void;
}) {
  const fb = draft.fact_block;

  function handleAccept() {
    const hasStrike = draft.suggested_strike != null;
    const hasSpread = draft.suggested_spread_strike != null;
    const leg: OptionLegDraft | null = hasStrike
      ? {
          option_type: draft.direction === "bullish" ? "call" : "put",
          strike: draft.suggested_strike,
          strike2: draft.suggested_spread_strike,
          option_expiration: fb.expiration_used ?? null,
          spread_type: hasSpread
            ? (draft.direction === "bullish" ? "bull_call_spread" : "bear_put_spread")
            : null,
        }
      : null;
    onAccept(draft.suggested_target, draft.reasoning, leg);
  }

  return (
    <div className="rounded-lg border bg-muted/30 p-4 space-y-3 text-sm">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          AI Draft — {draft.aggressiveness} {draft.direction}
        </p>
        <span className="text-xs text-muted-foreground">{draft.model_used}</span>
      </div>

      {draft.realism_flag && (
        <div className="rounded-md bg-amber-50 dark:bg-amber-900/30 border border-amber-300 dark:border-amber-700 px-3 py-2">
          <p className="text-xs font-semibold text-amber-800 dark:text-amber-300 mb-0.5">⚠ Realism Flag</p>
          <p className="text-xs text-amber-800 dark:text-amber-300">{draft.realism_flag}</p>
        </div>
      )}

      <div className="space-y-1">
        {draft.strategy && <p className="font-medium">{draft.strategy}</p>}
        <div className="flex gap-4 flex-wrap text-muted-foreground text-sm">
          {draft.suggested_target != null && (
            <span>Target: <span className="text-foreground font-medium">${draft.suggested_target.toFixed(2)}</span></span>
          )}
          {draft.suggested_strike != null && (
            <span>Strike: <span className="text-foreground font-medium">${draft.suggested_strike.toFixed(2)}</span></span>
          )}
          {draft.suggested_spread_strike != null && (
            <span>Spread leg: <span className="text-foreground font-medium">${draft.suggested_spread_strike.toFixed(2)}</span></span>
          )}
        </div>
      </div>

      <p className="text-muted-foreground leading-relaxed">{draft.reasoning}</p>

      <div className="rounded-md bg-background border px-3 py-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-muted-foreground">
        <span>Price: <span className="text-foreground">${fb.current_price.toFixed(2)}</span></span>
        <span>Implied move: <span className="text-foreground">±{fb.expected_move_pct?.toFixed(1) ?? "—"}% (±${fb.expected_move_dollars?.toFixed(2) ?? "—"})</span></span>
        <span>Implied range: <span className="text-foreground">${fb.implied_range_low?.toFixed(2) ?? "—"} – ${fb.implied_range_high?.toFixed(2) ?? "—"}</span></span>
        <span>Earnings: <span className="text-foreground">{fb.earnings_date ?? "—"}</span></span>
        <span>Hist avg: <span className="text-foreground">±{fb.hist_avg_abs_move_pct?.toFixed(2) ?? "—"}%</span></span>
        <span>Hist max: <span className="text-foreground">±{fb.hist_max_abs_move_pct?.toFixed(2) ?? "—"}%</span></span>
        <span>Beat rate: <span className="text-foreground">{fb.beat_rate_pct?.toFixed(1) ?? "—"}%</span></span>
        <span>RV rank: <span className="text-foreground">{fb.rv_rank?.toFixed(0) ?? "—"}/100</span></span>
      </div>

      <p className="text-xs text-muted-foreground italic">
        Data-grounded suggestion — not a recommendation. Review and edit before saving.
      </p>

      <button
        type="button"
        onClick={handleAccept}
        className="rounded-md border bg-background px-3 py-1.5 text-sm hover:bg-accent transition-colors"
      >
        {draft.suggested_strike != null
          ? "Accept → fill target, reasoning & option leg"
          : "Accept → fill target & reasoning"}
      </button>
    </div>
  );
}

// ── Create form ───────────────────────────────────────────────────────────────

interface OptionLegState {
  option_type: "call" | "put";
  strike: string;
  option_expiration: string;
  contracts: string;
  strike2: string;
  spread_type: string;
}

function CreateThesisForm({ onCreated }: { onCreated: (t: Thesis) => void }) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [draft, setDraft] = useState<ThesisDraftRead | null>(null);
  const [aggressiveness, setAggressiveness] = useState<"conservative" | "moderate" | "aggressive">("moderate");

  const [optionLegEnabled, setOptionLegEnabled] = useState(false);
  const [fromAiDraft, setFromAiDraft] = useState(false);
  const [optionLeg, setOptionLeg] = useState<OptionLegState>({
    option_type: "call",
    strike: "",
    option_expiration: "",
    contracts: "1",
    strike2: "",
    spread_type: "",
  });

  const defaultDate = () => {
    const d = new Date();
    d.setMonth(d.getMonth() + 3);
    return d.toISOString().slice(0, 10);
  };

  const [form, setForm] = useState<ThesisCreate>({
    symbol: "",
    direction: "bullish",
    conviction: 3,
    target_date: defaultDate(),
  });

  function resetForm() {
    setForm({ symbol: "", direction: "bullish", conviction: 3, target_date: defaultDate() });
    setDraft(null);
    setDraftError(null);
    setOptionLegEnabled(false);
    setFromAiDraft(false);
    setOptionLeg({ option_type: "call", strike: "", option_expiration: "", contracts: "1", strike2: "", spread_type: "" });
    setError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const optionPayload: Partial<ThesisCreate> =
        optionLegEnabled && optionLeg.strike && optionLeg.option_expiration
          ? {
              option_type: optionLeg.option_type,
              strike: parseFloat(optionLeg.strike),
              option_expiration: optionLeg.option_expiration,
              contracts: parseInt(optionLeg.contracts) || 1,
              ...(optionLeg.strike2 ? { strike2: parseFloat(optionLeg.strike2) } : {}),
              ...(optionLeg.spread_type ? { spread_type: optionLeg.spread_type } : {}),
              from_ai_draft: fromAiDraft,
            }
          : {};
      const thesis = await api.theses.create({ ...form, ...optionPayload });
      onCreated(thesis);
      setOpen(false);
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create thesis");
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="rounded-md bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:opacity-90 transition-opacity"
      >
        + New Thesis
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-lg border bg-card p-5 space-y-4 max-w-xl">
      <h3 className="font-semibold text-base">New Thesis</h3>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Symbol</label>
          <input
            className="w-full rounded-md border bg-background px-3 py-1.5 text-sm uppercase"
            placeholder="AAPL"
            value={form.symbol}
            onChange={e => setForm(f => ({ ...f, symbol: e.target.value.toUpperCase() }))}
            required
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Direction</label>
          <select
            className="w-full rounded-md border bg-background px-3 py-1.5 text-sm"
            value={form.direction}
            onChange={e => setForm(f => ({ ...f, direction: e.target.value as ThesisCreate["direction"] }))}
          >
            <option value="bullish">Bullish</option>
            <option value="bearish">Bearish</option>
            <option value="neutral">Neutral</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Conviction (1–5)</label>
          <input
            type="number" min={1} max={5}
            className="w-full rounded-md border bg-background px-3 py-1.5 text-sm"
            value={form.conviction}
            onChange={e => setForm(f => ({ ...f, conviction: parseInt(e.target.value) }))}
            required
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Target Date</label>
          <input
            type="date"
            className="w-full rounded-md border bg-background px-3 py-1.5 text-sm"
            value={form.target_date}
            onChange={e => setForm(f => ({ ...f, target_date: e.target.value }))}
            required
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Price Target (optional)</label>
          <input
            type="number" step="0.01" min="0"
            className="w-full rounded-md border bg-background px-3 py-1.5 text-sm"
            placeholder="e.g. 220.00"
            value={form.price_target ?? ""}
            onChange={e => setForm(f => ({ ...f, price_target: e.target.value ? parseFloat(e.target.value) : undefined }))}
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Catalyst (optional)</label>
          <input
            className="w-full rounded-md border bg-background px-3 py-1.5 text-sm"
            placeholder="e.g. Q2 earnings beat"
            value={form.catalyst ?? ""}
            onChange={e => setForm(f => ({ ...f, catalyst: e.target.value || undefined }))}
          />
        </div>
      </div>

      <div>
        <label className="text-xs text-muted-foreground mb-1 block">Reasoning (optional)</label>
        <textarea
          className="w-full rounded-md border bg-background px-3 py-1.5 text-sm resize-none"
          rows={3}
          placeholder="Why do you have this view?"
          value={form.reasoning ?? ""}
          onChange={e => setForm(f => ({ ...f, reasoning: e.target.value || undefined }))}
        />
      </div>

      {/* ── Draft with AI ──────────────────────────────────────────────── */}
      {form.direction !== "neutral" && (
        <div className="rounded-md border border-dashed bg-muted/20 px-4 py-3 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Draft with AI</span>
            <div className="flex items-center gap-2">
              <select
                className="rounded-md border bg-background px-2 py-1 text-xs"
                value={aggressiveness}
                onChange={e => setAggressiveness(e.target.value as typeof aggressiveness)}
                disabled={drafting}
              >
                <option value="conservative">Conservative</option>
                <option value="moderate">Moderate</option>
                <option value="aggressive">Aggressive</option>
              </select>
              <button
                type="button"
                disabled={drafting || !form.symbol}
                onClick={async () => {
                  if (!form.symbol) return;
                  setDrafting(true);
                  setDraftError(null);
                  setDraft(null);
                  try {
                    const result = await api.theses.draft({
                      symbol: form.symbol,
                      direction: form.direction as "bullish" | "bearish",
                      aggressiveness,
                      proposed_target: form.price_target,
                    });
                    setDraft(result);
                  } catch (err) {
                    setDraftError(err instanceof Error ? err.message : "Draft failed");
                  } finally {
                    setDrafting(false);
                  }
                }}
                className="rounded-md bg-secondary text-secondary-foreground px-3 py-1 text-xs font-medium hover:opacity-90 disabled:opacity-50"
              >
                {drafting ? "Drafting…" : "Generate draft"}
              </button>
            </div>
          </div>
          {draftError && <p className="text-xs text-red-500">{draftError}</p>}
          {drafting && (
            <div className="animate-pulse space-y-2">
              <div className="h-3 bg-muted rounded w-3/4" />
              <div className="h-3 bg-muted rounded w-1/2" />
              <div className="h-3 bg-muted rounded w-2/3" />
            </div>
          )}
          {draft && (
            <DraftPanel
              draft={draft}
              onAccept={(target, reasoning, leg) => {
                setForm(f => ({
                  ...f,
                  price_target: target ?? f.price_target,
                  reasoning: reasoning ?? f.reasoning,
                }));
                if (leg) {
                  setOptionLegEnabled(true);
                  setFromAiDraft(true);
                  setOptionLeg({
                    option_type: leg.option_type,
                    strike: leg.strike != null ? String(leg.strike) : "",
                    option_expiration: leg.option_expiration ?? "",
                    contracts: "1",
                    strike2: leg.strike2 != null ? String(leg.strike2) : "",
                    spread_type: leg.spread_type ?? "",
                  });
                }
              }}
            />
          )}
        </div>
      )}

      {/* ── Option leg (manual or from AI draft) ──────────────────────── */}
      <div className="rounded-md border border-dashed bg-muted/10 px-4 py-3 space-y-3">
        <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={optionLegEnabled}
            onChange={e => setOptionLegEnabled(e.target.checked)}
          />
          Track option position
          {fromAiDraft && optionLegEnabled && (
            <span className="ml-1 text-blue-500">(from AI draft)</span>
          )}
        </label>
        {optionLegEnabled && (
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Type</label>
              <select
                className="w-full rounded-md border bg-background px-2 py-1.5 text-xs"
                value={optionLeg.option_type}
                onChange={e => setOptionLeg(l => ({ ...l, option_type: e.target.value as "call" | "put" }))}
              >
                <option value="call">Call</option>
                <option value="put">Put</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Strike</label>
              <input
                type="number" step="0.5"
                className="w-full rounded-md border bg-background px-2 py-1.5 text-xs"
                placeholder="e.g. 195"
                value={optionLeg.strike}
                onChange={e => setOptionLeg(l => ({ ...l, strike: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Expiration</label>
              <input
                type="date"
                className="w-full rounded-md border bg-background px-2 py-1.5 text-xs"
                value={optionLeg.option_expiration}
                onChange={e => setOptionLeg(l => ({ ...l, option_expiration: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Contracts</label>
              <input
                type="number" min="1" step="1"
                className="w-full rounded-md border bg-background px-2 py-1.5 text-xs"
                value={optionLeg.contracts}
                onChange={e => setOptionLeg(l => ({ ...l, contracts: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Spread strike (opt.)</label>
              <input
                type="number" step="0.5"
                className="w-full rounded-md border bg-background px-2 py-1.5 text-xs"
                placeholder="e.g. 205"
                value={optionLeg.strike2}
                onChange={e => setOptionLeg(l => ({ ...l, strike2: e.target.value }))}
              />
            </div>
          </div>
        )}
        {optionLegEnabled && (
          <p className="text-xs text-muted-foreground">Entry premium will be captured from the live chain at creation.</p>
        )}
      </div>

      <p className="text-xs text-muted-foreground">Entry price will be captured from the live quote at creation.</p>

      {error && <p className="text-sm text-red-500">{error}</p>}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded-md bg-primary text-primary-foreground px-4 py-1.5 text-sm font-medium hover:opacity-90 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save Thesis"}
        </button>
        <button
          type="button"
          onClick={() => { setOpen(false); resetForm(); }}
          className="rounded-md border px-4 py-1.5 text-sm hover:bg-accent"
        >
          Cancel
        </button>
      </div>
    </form>
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
            placeholder="Use live quote if blank"
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
        <p className="text-xs text-muted-foreground">Option P&L will be computed from the live chain at resolution.</p>
      )}
      {error && <p className="text-sm text-red-500">{error}</p>}
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
  onResolved,
  onDeleted,
}: {
  thesis: Thesis;
  mark?: ThesisMarkRead | "loading" | "error";
  stockMark?: ThesisStockMarkRead | "loading" | "error";
  refreshing?: boolean;
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
    <div className={`rounded-lg border bg-card p-4 space-y-2 ${deleting ? "opacity-40" : ""}`}>
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <Link href={`/tickers/${thesis.ticker_symbol}`} className="font-semibold hover:underline">
            {thesis.ticker_symbol ?? "—"}
          </Link>
          <span className={`text-sm font-medium capitalize ${DIRECTION_COLOR[thesis.direction]}`}>
            {thesis.direction}
          </span>
          <ConvictionDots n={thesis.conviction} />
          {thesis.is_due && isOpen && (
            <span className="text-xs bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 px-1.5 py-0.5 rounded">
              Due
            </span>
          )}
          {needsManual && (
            <span className="text-xs bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300 px-1.5 py-0.5 rounded">
              Needs manual resolution
            </span>
          )}
          {thesis.from_ai_draft && (
            <span className="text-xs bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 px-1.5 py-0.5 rounded">
              AI
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

      {/* ── Option P&L headline (option theses only) ───────────────────── */}
      <OptionPnlSection thesis={thesis} mark={mark} refreshing={refreshing} />

      {/* ── Stock price mark (stock-only theses, open) ─────────────────── */}
      <StockPriceMark thesis={thesis} mark={stockMark} refreshing={refreshing} />

      {/* ── Compact fact row ───────────────────────────────────────────── */}
      <div className="flex items-center gap-3 text-sm flex-wrap text-muted-foreground">
        <span>Entry: <span className="text-foreground font-medium">{fmtPrice(thesis.entry_price)}</span></span>
        {thesis.price_target && (
          <span>→ Target: <span className="text-foreground font-medium">{fmtPrice(thesis.price_target)}</span></span>
        )}
        <span>By: <span className="text-foreground">{fmtDate(thesis.target_date)}</span></span>
        {thesis.catalyst && (
          <span className="text-muted-foreground">· {thesis.catalyst}</span>
        )}
      </div>

      {/* ── Option entry details (when tracked) ───────────────────────── */}
      {thesis.entry_premium && (
        <div className="flex items-center gap-3 flex-wrap">
          <p className="text-xs text-muted-foreground">
            Option entry: <span className="text-foreground">${parseFloat(thesis.entry_premium).toFixed(2)} mid</span>
            {thesis.contracts > 1 && ` · ${thesis.contracts} contracts`}
          </p>
          <Link
            href={`/theses/${thesis.id}`}
            className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
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
                    ? "text-emerald-600" : "text-red-500"
                  : thesis.direction === "bearish"
                  ? parseFloat(thesis.price_at_resolution ?? "0") <= parseFloat(thesis.entry_price ?? "0")
                    ? "text-emerald-600" : "text-red-500"
                  : ""
              }>
                ({pctChange(thesis.entry_price, thesis.price_at_resolution)})
              </span>
            </span>
            {thesis.direction_correct != null && (
              <span>
                Direction:{" "}
                <span className={thesis.direction_correct ? "text-emerald-600 dark:text-emerald-400" : "text-red-500"}>
                  {thesis.direction_correct ? "✓" : "✗"}
                </span>
              </span>
            )}
            {thesis.target_reached != null && (
              <span>
                Target:{" "}
                <span className={thesis.target_reached ? "text-emerald-600 dark:text-emerald-400" : "text-red-500"}>
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
                  ? "text-emerald-600 dark:text-emerald-400 font-medium"
                  : "text-red-500 dark:text-red-400 font-medium"
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
              className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
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

  function handleCreated(t: Thesis) {
    setTheses(prev => [t, ...prev]);
    if (t.option_type) {
      if (!markRequested.current.has(t.id)) {
        markRequested.current.add(t.id);
        setMarks(prev => ({ ...prev, [t.id]: "loading" }));
        api.theses.mark(t.id)
          .then(data => setMarks(prev => ({ ...prev, [t.id]: data })))
          .catch(() => setMarks(prev => ({ ...prev, [t.id]: "error" })));
      }
    } else {
      if (!stockMarkRequested.current.has(t.id)) {
        stockMarkRequested.current.add(t.id);
        setStockMarks(prev => ({ ...prev, [t.id]: "loading" }));
        api.theses.stockMark(t.id)
          .then(data => setStockMarks(prev => ({ ...prev, [t.id]: data })))
          .catch(() => setStockMarks(prev => ({ ...prev, [t.id]: "error" })));
      }
    }
  }

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
            <h1 className="text-2xl font-bold tracking-tight">Thesis Tracker</h1>
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
              className={`px-3 py-1 rounded-md text-sm capitalize transition-colors ${
                statusFilter === f
                  ? "bg-primary text-primary-foreground"
                  : "hover:bg-accent text-muted-foreground"
              }`}
            >
              {f}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="rounded-lg border bg-card p-4 animate-pulse space-y-2">
                <div className="h-4 bg-muted rounded w-32" />
                <div className="h-3 bg-muted rounded w-48" />
                <div className="h-3 bg-muted rounded w-64" />
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-muted-foreground text-sm py-8 text-center">
            {statusFilter === "all" ? "No theses yet. Create one above." : `No ${statusFilter} theses.`}
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
