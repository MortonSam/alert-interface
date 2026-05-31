"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, type Thesis, type ThesisCreate, type ThesisDraftRead, type ThesisResolve, type SelfGrade } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPrice(v: string | null | undefined): string {
  if (v == null) return "—";
  const n = parseFloat(v);
  return isNaN(n) ? "—" : `$${n.toFixed(2)}`;
}

function fmtDate(v: string): string {
  // "YYYY-MM-DD" → "MMM D, YYYY"
  const [y, m, d] = v.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function pctChange(entry: string | null, resolution: string | null): string {
  if (!entry || !resolution) return "";
  const e = parseFloat(entry);
  const r = parseFloat(resolution);
  if (!e) return "";
  const pct = ((r - e) / e) * 100;
  return (pct >= 0 ? "+" : "") + pct.toFixed(1) + "%";
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

// ── Draft panel ───────────────────────────────────────────────────────────────

function DraftPanel({
  draft,
  onAccept,
}: {
  draft: ThesisDraftRead;
  onAccept: (target: number | null, reasoning: string | null) => void;
}) {
  const fb = draft.fact_block;
  return (
    <div className="rounded-lg border bg-muted/30 p-4 space-y-3 text-sm">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          AI Draft — {draft.aggressiveness} {draft.direction}
        </p>
        <span className="text-xs text-muted-foreground">{draft.model_used}</span>
      </div>

      {/* Realism flag — shown first and prominently if present */}
      {draft.realism_flag && (
        <div className="rounded-md bg-amber-50 dark:bg-amber-900/30 border border-amber-300 dark:border-amber-700 px-3 py-2">
          <p className="text-xs font-semibold text-amber-800 dark:text-amber-300 mb-0.5">⚠ Realism Flag</p>
          <p className="text-xs text-amber-800 dark:text-amber-300">{draft.realism_flag}</p>
        </div>
      )}

      {/* Core suggestion */}
      <div className="space-y-1">
        {draft.strategy && (
          <p className="font-medium">{draft.strategy}</p>
        )}
        <div className="flex gap-4 flex-wrap text-muted-foreground">
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

      {/* Reasoning */}
      <p className="text-muted-foreground leading-relaxed">{draft.reasoning}</p>

      {/* Data context strip */}
      <div className="rounded-md bg-background border px-3 py-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-muted-foreground">
        <span>Price: <span className="text-foreground">${fb.current_price.toFixed(2)}</span></span>
        <span>Implied move: <span className="text-foreground">±{fb.expected_move_pct?.toFixed(1) ?? "—"}% (±${fb.expected_move_dollars?.toFixed(2) ?? "—"})</span></span>
        <span>Implied range: <span className="text-foreground">${fb.implied_range_low?.toFixed(2) ?? "—"} – ${fb.implied_range_high?.toFixed(2) ?? "—"}</span></span>
        <span>Earnings: <span className="text-foreground">{fb.earnings_date ?? "—"}</span></span>
        <span>Hist avg move: <span className="text-foreground">±{fb.hist_avg_abs_move_pct?.toFixed(2) ?? "—"}%</span></span>
        <span>Hist max move: <span className="text-foreground">±{fb.hist_max_abs_move_pct?.toFixed(2) ?? "—"}%</span></span>
        <span>Beat rate: <span className="text-foreground">{fb.beat_rate_pct?.toFixed(1) ?? "—"}%</span></span>
        <span>RV rank: <span className="text-foreground">{fb.rv_rank?.toFixed(0) ?? "—"}/100</span></span>
      </div>

      <p className="text-xs text-muted-foreground italic">
        Data-grounded suggestion — not a recommendation. Direction is yours; review and edit before saving.
      </p>

      <button
        type="button"
        onClick={() => onAccept(draft.suggested_target, draft.reasoning)}
        className="rounded-md border bg-background px-3 py-1.5 text-sm hover:bg-accent transition-colors"
      >
        Accept suggestion → fill target &amp; reasoning
      </button>
    </div>
  );
}


// ── Create form ───────────────────────────────────────────────────────────────

function CreateThesisForm({ onCreated }: { onCreated: (t: Thesis) => void }) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [draft, setDraft] = useState<ThesisDraftRead | null>(null);
  const [aggressiveness, setAggressiveness] = useState<"conservative" | "moderate" | "aggressive">("moderate");

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

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const thesis = await api.theses.create(form);
      onCreated(thesis);
      setOpen(false);
      setForm({ symbol: "", direction: "bullish", conviction: 3, target_date: defaultDate() });
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
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border bg-card p-5 space-y-4 max-w-xl"
    >
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
            type="number"
            min={1}
            max={5}
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
            type="number"
            step="0.01"
            min="0"
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
              onAccept={(target, reasoning) => {
                setForm(f => ({
                  ...f,
                  price_target: target ?? f.price_target,
                  reasoning: reasoning ?? f.reasoning,
                }));
              }}
            />
          )}
        </div>
      )}

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
          onClick={() => { setOpen(false); setError(null); }}
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
  const [form, setForm] = useState<ThesisResolve>({
    reflection: "",
    self_grade: "right",
  });
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
            type="number"
            step="0.01"
            min="0"
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
  onResolved,
  onDeleted,
}: {
  thesis: Thesis;
  onResolved: (t: Thesis) => void;
  onDeleted: (id: string) => void;
}) {
  const [resolving, setResolving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const isOpen = thesis.status === "open" || thesis.status === "needs_manual_resolution";
  const needsManual = thesis.status === "needs_manual_resolution";

  async function handleDelete() {
    if (!confirm(`Delete thesis for ${thesis.ticker_symbol}?`)) return;
    setDeleting(true);
    try {
      await api.theses.delete(thesis.id);
      onDeleted(thesis.id);
    } catch {
      setDeleting(false);
    }
  }

  return (
    <div className={`rounded-lg border bg-card p-4 space-y-2 ${deleting ? "opacity-40" : ""}`}>
      {/* Header row */}
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
        </div>
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="text-xs text-muted-foreground hover:text-destructive shrink-0"
        >
          Delete
        </button>
      </div>

      {/* Price row */}
      <div className="flex items-center gap-4 text-sm flex-wrap">
        <span className="text-muted-foreground">
          Entry: <span className="text-foreground font-medium">{fmtPrice(thesis.entry_price)}</span>
        </span>
        {thesis.price_target && (
          <span className="text-muted-foreground">
            Target: <span className="text-foreground font-medium">{fmtPrice(thesis.price_target)}</span>
          </span>
        )}
        <span className="text-muted-foreground">
          By: <span className="text-foreground">{fmtDate(thesis.target_date)}</span>
        </span>
      </div>

      {/* Catalyst / reasoning */}
      {thesis.catalyst && (
        <p className="text-sm text-muted-foreground">
          <span className="font-medium text-foreground">Catalyst:</span> {thesis.catalyst}
        </p>
      )}
      {thesis.reasoning && (
        <p className="text-sm text-muted-foreground">{thesis.reasoning}</p>
      )}

      {/* Resolution outcome */}
      {thesis.status === "resolved" && (
        <div className="rounded-md bg-muted/40 px-3 py-2 space-y-1">
          <div className="flex items-center gap-3 flex-wrap text-sm">
            <span className="text-muted-foreground">
              Resolved: <span className="text-foreground font-medium">{fmtPrice(thesis.price_at_resolution)}</span>
              {" "}
              <span className={thesis.direction === "bullish"
                ? parseFloat(thesis.price_at_resolution ?? "0") >= parseFloat(thesis.entry_price ?? "0") ? "text-emerald-600" : "text-red-500"
                : thesis.direction === "bearish"
                ? parseFloat(thesis.price_at_resolution ?? "0") <= parseFloat(thesis.entry_price ?? "0") ? "text-emerald-600" : "text-red-500"
                : ""}>
                ({pctChange(thesis.entry_price, thesis.price_at_resolution)})
              </span>
            </span>
            <span>
              Direction:{" "}
              <span className={thesis.direction_correct ? "text-emerald-600 dark:text-emerald-400" : "text-red-500"}>
                {thesis.direction_correct ? "Correct" : "Incorrect"}
              </span>
            </span>
            {thesis.target_reached !== null && (
              <span>
                Target:{" "}
                <span className={thesis.target_reached ? "text-emerald-600 dark:text-emerald-400" : "text-red-500"}>
                  {thesis.target_reached ? "Reached" : "Not reached"}
                </span>
              </span>
            )}
            {thesis.self_grade && (
              <span className={`font-medium ${GRADE_COLOR[thesis.self_grade]}`}>
                {GRADE_LABEL[thesis.self_grade]}
              </span>
            )}
          </div>
          {thesis.reflection && (
            <p className="text-sm text-muted-foreground italic">&ldquo;{thesis.reflection}&rdquo;</p>
          )}
        </div>
      )}

      {/* Resolve button / form */}
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

export default function ThesesPage() {
  const [theses, setTheses] = useState<Thesis[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<"all" | "open" | "resolved">("all");
  const initialized = useRef(false);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    api.theses.list().then(data => {
      setTheses(data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  function handleCreated(t: Thesis) {
    setTheses(prev => [t, ...prev]);
  }

  function handleResolved(updated: Thesis) {
    setTheses(prev => prev.map(t => t.id === updated.id ? updated : t));
  }

  function handleDeleted(id: string) {
    setTheses(prev => prev.filter(t => t.id !== id));
  }

  const filtered = theses.filter(t => {
    if (statusFilter === "open") return t.status === "open" || t.status === "needs_manual_resolution";
    if (statusFilter === "resolved") return t.status === "resolved";
    return true;
  });

  const openCount = theses.filter(t => t.status === "open" || t.status === "needs_manual_resolution").length;
  const dueCount = theses.filter(t => t.is_due && (t.status === "open" || t.status === "needs_manual_resolution")).length;

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

        <CreateThesisForm onCreated={handleCreated} />

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
