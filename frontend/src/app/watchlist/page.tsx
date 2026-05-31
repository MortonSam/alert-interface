"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import {
  api,
  type Watchlist,
  type WatchlistTicker,
  type TickerQuote,
  type ExpectedMove,
  type RealizedVol,
  type Ticker,
} from "@/lib/api";

// ── Row state ─────────────────────────────────────────────────────────────────

interface RowState {
  symbol: string;
  item: WatchlistTicker;
  quoteStatus: "loading" | "done" | "error";
  quote: TickerQuote | null;
  emStatus: "loading" | "done" | "error";
  em: ExpectedMove | null;
  rvStatus: "loading" | "done" | "error";
  rv: RealizedVol | null;
}

// ── Formatters ────────────────────────────────────────────────────────────────

function fmtPrice(n: number | null): string {
  return n == null ? "—" : `$${n.toFixed(2)}`;
}

function fmtDate(d: string | null): string {
  if (!d) return "—";
  const [y, m, day] = d.split("-").map(Number);
  return new Date(y, m - 1, day).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

// ── Small sub-components ──────────────────────────────────────────────────────

function Skeleton({ w = "w-16" }: { w?: string }) {
  return <div className={`${w} h-4 bg-muted rounded animate-pulse`} />;
}

function ChangeCell({ quote, status }: { quote: TickerQuote | null; status: string }) {
  if (status === "loading") return <Skeleton w="w-14" />;
  if (!quote || quote.change_pct == null)
    return <span className="text-muted-foreground text-xs">—</span>;
  const pct = quote.change_pct;
  const color =
    pct > 0
      ? "text-emerald-600 dark:text-emerald-400"
      : pct < 0
      ? "text-red-500 dark:text-red-400"
      : "text-muted-foreground";
  return (
    <span className={`font-medium ${color}`}>
      {pct > 0 ? "+" : ""}
      {pct.toFixed(2)}%
    </span>
  );
}

function ImpliedMoveCell({ em, status }: { em: ExpectedMove | null; status: string }) {
  if (status === "loading") return <Skeleton w="w-12" />;
  if (!em || em.expected_move_pct == null)
    return <span className="text-muted-foreground text-xs">—</span>;
  return (
    <span className="font-mono text-sm">
      ±{(em.expected_move_pct * 100).toFixed(1)}%
    </span>
  );
}

function RVRankCell({ rv, status }: { rv: RealizedVol | null; status: string }) {
  if (status === "loading") return <Skeleton w="w-12" />;
  if (!rv || rv.rv_rank == null)
    return <span className="text-muted-foreground text-xs">—</span>;
  const rank = rv.rv_rank;
  const color =
    rank > 60
      ? "text-amber-600 dark:text-amber-400"
      : rank < 40
      ? "text-blue-500 dark:text-blue-400"
      : "text-muted-foreground";
  return <span className={`${color} tabular-nums`}>{rank.toFixed(0)}/100</span>;
}

function WatchlistRow({
  row,
  onRemove,
  removing,
}: {
  row: RowState;
  onRemove: () => void;
  removing: boolean;
}) {
  const { item, quote, quoteStatus, em, emStatus, rv, rvStatus } = row;
  const ticker = item.ticker;

  return (
    <tr
      className={`border-b border-border transition-colors ${
        removing ? "opacity-40" : "hover:bg-muted/30"
      }`}
    >
      <td className="py-3 px-4">
        <Link
          href={`/tickers/${ticker.symbol}`}
          className="font-semibold text-foreground hover:underline"
        >
          {ticker.symbol}
        </Link>
      </td>
      <td className="py-3 px-4 text-sm text-muted-foreground">
        <span className="line-clamp-1 max-w-[180px] block">{ticker.name ?? "—"}</span>
      </td>
      <td className="py-3 px-4 font-mono text-sm">
        {quoteStatus === "loading" ? (
          <Skeleton w="w-16" />
        ) : (
          fmtPrice(quote?.price ?? null)
        )}
      </td>
      <td className="py-3 px-4 text-sm">
        <ChangeCell quote={quote} status={quoteStatus} />
      </td>
      <td className="py-3 px-4 text-sm">
        {emStatus === "loading" ? (
          <Skeleton w="w-16" />
        ) : em?.earnings_date ? (
          <span className="inline-flex items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/30 px-1 py-0.5 rounded">
              EPS
            </span>
            <span className="text-muted-foreground">{fmtDate(em.earnings_date)}</span>
          </span>
        ) : (
          <span className="text-muted-foreground text-xs">—</span>
        )}
      </td>
      <td className="py-3 px-4 text-sm">
        <ImpliedMoveCell em={em} status={emStatus} />
      </td>
      <td className="py-3 px-4 text-sm">
        <RVRankCell rv={rv} status={rvStatus} />
      </td>
      <td className="py-3 px-4">
        <button
          onClick={onRemove}
          disabled={removing}
          className="text-muted-foreground/50 hover:text-red-500 transition-colors text-sm leading-none disabled:cursor-not-allowed"
          title="Remove from watchlist"
        >
          ✕
        </button>
      </td>
    </tr>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WatchlistPage() {
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [wlStatus, setWlStatus] = useState<"loading" | "done" | "error">("loading");
  const [activeWlId, setActiveWlId] = useState<string | null>(null);

  const [rows, setRows] = useState<RowState[]>([]);
  const [removingIds, setRemovingIds] = useState<Set<string>>(new Set());

  // All tickers for add-ticker autocomplete
  const [allTickers, setAllTickers] = useState<Ticker[]>([]);
  const [addInput, setAddInput] = useState("");
  const [addStatus, setAddStatus] = useState<"idle" | "adding">("idle");
  const [addError, setAddError] = useState<string | null>(null);

  // Create-watchlist form
  const [showCreate, setShowCreate] = useState(false);
  const [newWlName, setNewWlName] = useState("My Watchlist");
  const [creating, setCreating] = useState(false);

  // Track which wlId we've already initialized rows for (to avoid double-init)
  const initializedRef = useRef<string | null>(null);

  const activeWatchlist = watchlists.find((w) => w.id === activeWlId) ?? null;

  // ── Load watchlists + all tickers on mount ──────────────────────────────────

  useEffect(() => {
    Promise.all([api.watchlists.list(), api.tickers.list(true)]).then(
      ([wls, tickers]) => {
        setWatchlists(wls);
        if (wls.length > 0) setActiveWlId(wls[0].id);
        setAllTickers(tickers);
        setWlStatus("done");
      }
    ).catch(() => setWlStatus("error"));
  }, []);

  // ── Initialize rows + fire fetches when active watchlist changes ────────────

  useEffect(() => {
    if (!activeWlId || !activeWatchlist) return;
    // Avoid re-initializing if already done for this watchlist ID
    if (initializedRef.current === activeWlId) return;
    initializedRef.current = activeWlId;

    const items = activeWatchlist.items;

    // Seed all rows as loading
    setRows(
      items.map((item) => ({
        symbol: item.ticker.symbol,
        item,
        quoteStatus: "loading",
        quote: null,
        emStatus: "loading",
        em: null,
        rvStatus: "loading",
        rv: null,
      }))
    );

    // Parallel fetches per ticker
    for (const item of items) {
      const sym = item.ticker.symbol;
      fireRowFetches(sym);
    }
  }, [activeWlId, activeWatchlist]);

  function fireRowFetches(sym: string) {
    api.tickers
      .quote(sym)
      .then((q) =>
        setRows((prev) =>
          prev.map((r) => (r.symbol === sym ? { ...r, quote: q, quoteStatus: "done" } : r))
        )
      )
      .catch(() =>
        setRows((prev) =>
          prev.map((r) => (r.symbol === sym ? { ...r, quoteStatus: "error" } : r))
        )
      );

    api.tickers
      .expectedMove(sym)
      .then((em) =>
        setRows((prev) =>
          prev.map((r) => (r.symbol === sym ? { ...r, em, emStatus: "done" } : r))
        )
      )
      .catch(() =>
        setRows((prev) =>
          prev.map((r) => (r.symbol === sym ? { ...r, emStatus: "error" } : r))
        )
      );

    api.tickers
      .realizedVol(sym)
      .then((rv) =>
        setRows((prev) =>
          prev.map((r) => (r.symbol === sym ? { ...r, rv, rvStatus: "done" } : r))
        )
      )
      .catch(() =>
        setRows((prev) =>
          prev.map((r) => (r.symbol === sym ? { ...r, rvStatus: "error" } : r))
        )
      );
  }

  // ── Refresh quotes ──────────────────────────────────────────────────────────

  const handleRefresh = useCallback(() => {
    setRows((prev) =>
      prev.map((r) => ({ ...r, quoteStatus: "loading" as const, quote: null }))
    );
    rows.forEach((r) => {
      api.tickers
        .quote(r.symbol)
        .then((q) =>
          setRows((prev) =>
            prev.map((row) =>
              row.symbol === r.symbol ? { ...row, quote: q, quoteStatus: "done" } : row
            )
          )
        )
        .catch(() =>
          setRows((prev) =>
            prev.map((row) =>
              row.symbol === r.symbol ? { ...row, quoteStatus: "error" } : row
            )
          )
        );
    });
  }, [rows]);

  // ── Add ticker ──────────────────────────────────────────────────────────────

  const handleAdd = useCallback(async () => {
    if (!activeWlId || !addInput.trim()) return;
    const sym = addInput.trim().toUpperCase();
    const ticker = allTickers.find((t) => t.symbol === sym);
    if (!ticker) {
      setAddError(`"${sym}" not found. Check the symbol and try again.`);
      return;
    }
    if (rows.some((r) => r.symbol === sym)) {
      setAddError(`${sym} is already in this watchlist.`);
      return;
    }
    setAddStatus("adding");
    setAddError(null);
    try {
      const updated = await api.watchlists.addTicker(activeWlId, ticker.id);
      setWatchlists((prev) => prev.map((w) => (w.id === activeWlId ? updated : w)));

      // Find the newly added item and seed a loading row
      const newItem = updated.items.find((i) => i.ticker_id === ticker.id);
      if (newItem) {
        setRows((prev) => [
          ...prev,
          {
            symbol: sym,
            item: newItem,
            quoteStatus: "loading",
            quote: null,
            emStatus: "loading",
            em: null,
            rvStatus: "loading",
            rv: null,
          },
        ]);
        fireRowFetches(sym);
      }

      setAddInput("");
      setAddStatus("idle");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setAddError(
        msg.includes("409") || msg.includes("unique")
          ? `${sym} is already in this watchlist.`
          : `Failed to add ${sym}.`
      );
      setAddStatus("idle");
    }
  }, [activeWlId, addInput, allTickers, rows]);

  // ── Remove ticker ───────────────────────────────────────────────────────────

  const handleRemove = useCallback(
    async (tickerId: string, symbol: string) => {
      if (!activeWlId) return;
      setRemovingIds((prev) => new Set(prev).add(tickerId));
      try {
        await api.watchlists.removeTicker(activeWlId, tickerId);
        setRows((prev) => prev.filter((r) => r.symbol !== symbol));
        setWatchlists((prev) =>
          prev.map((w) =>
            w.id === activeWlId
              ? { ...w, items: w.items.filter((i) => i.ticker_id !== tickerId) }
              : w
          )
        );
      } catch {
        // Keep the row if removal failed
        setRemovingIds((prev) => {
          const next = new Set(prev);
          next.delete(tickerId);
          return next;
        });
      }
    },
    [activeWlId]
  );

  // ── Create watchlist ────────────────────────────────────────────────────────

  const handleCreate = useCallback(async () => {
    if (!newWlName.trim()) return;
    setCreating(true);
    try {
      const wl = await api.watchlists.create({ name: newWlName.trim(), description: null });
      setWatchlists((prev) => [...prev, wl]);
      setActiveWlId(wl.id);
      initializedRef.current = null; // allow init effect to run for new wl
      setRows([]);
      setShowCreate(false);
      setNewWlName("My Watchlist");
    } catch {
      // silently fail; user can retry
    } finally {
      setCreating(false);
    }
  }, [newWlName]);

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-6xl mx-auto">

        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <Link href="/" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
                ← Home
              </Link>
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Watchlist</h1>
          </div>
          <div className="flex items-center gap-2">
            {rows.length > 0 && (
              <button
                onClick={handleRefresh}
                className="text-xs text-muted-foreground hover:text-foreground border rounded-md px-3 py-1.5 transition-colors"
              >
                Refresh prices
              </button>
            )}
            <button
              onClick={() => setShowCreate((v) => !v)}
              className="text-xs text-muted-foreground hover:text-foreground border rounded-md px-3 py-1.5 transition-colors"
            >
              + New watchlist
            </button>
          </div>
        </div>

        {/* Create watchlist form */}
        {showCreate && (
          <div className="mb-6 rounded-lg border bg-card px-5 py-4 flex items-center gap-3">
            <input
              type="text"
              value={newWlName}
              onChange={(e) => setNewWlName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              placeholder="Watchlist name"
              className="rounded-md border bg-background px-3 py-1.5 text-sm flex-1 max-w-xs focus:outline-none focus:ring-1 focus:ring-ring"
              autoFocus
            />
            <button
              onClick={handleCreate}
              disabled={creating}
              className="text-sm rounded-md bg-foreground text-background px-4 py-1.5 hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {creating ? "Creating…" : "Create"}
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
          </div>
        )}

        {/* Loading skeleton */}
        {wlStatus === "loading" && (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-12 bg-muted rounded-lg animate-pulse" />
            ))}
          </div>
        )}

        {/* Error */}
        {wlStatus === "error" && (
          <div className="rounded-lg border border-red-200 bg-red-50 dark:bg-red-900/20 px-5 py-4 text-sm text-red-700 dark:text-red-400">
            Failed to load watchlists. Is the backend running?
          </div>
        )}

        {/* Empty state — no watchlists */}
        {wlStatus === "done" && watchlists.length === 0 && !showCreate && (
          <div className="rounded-lg border bg-card px-8 py-12 text-center">
            <p className="text-muted-foreground mb-4">No watchlists yet.</p>
            <button
              onClick={() => setShowCreate(true)}
              className="text-sm rounded-md bg-foreground text-background px-5 py-2 hover:opacity-90 transition-opacity"
            >
              Create your first watchlist
            </button>
          </div>
        )}

        {/* Watchlist tabs (multiple watchlists) */}
        {wlStatus === "done" && watchlists.length > 1 && (
          <div className="flex gap-1 mb-5 border-b border-border">
            {watchlists.map((wl) => (
              <button
                key={wl.id}
                onClick={() => {
                  if (wl.id !== activeWlId) {
                    initializedRef.current = null;
                    setRows([]);
                    setActiveWlId(wl.id);
                  }
                }}
                className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                  wl.id === activeWlId
                    ? "border-foreground text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                {wl.name}
                <span className="ml-1.5 text-[11px] text-muted-foreground">
                  ({wl.items.length})
                </span>
              </button>
            ))}
          </div>
        )}

        {/* Active watchlist */}
        {wlStatus === "done" && activeWatchlist && (
          <div>
            {/* Watchlist name (single watchlist, no tabs) */}
            {watchlists.length === 1 && (
              <div className="mb-5 flex items-center gap-3">
                <h2 className="text-lg font-semibold">{activeWatchlist.name}</h2>
                <span className="text-sm text-muted-foreground">
                  {activeWatchlist.items.length}{" "}
                  {activeWatchlist.items.length === 1 ? "ticker" : "tickers"}
                </span>
              </div>
            )}

            {/* Add ticker row */}
            <div className="mb-5">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  list="ticker-symbols"
                  value={addInput}
                  onChange={(e) => {
                    setAddInput(e.target.value.toUpperCase());
                    setAddError(null);
                  }}
                  onKeyDown={(e) => e.key === "Enter" && handleAdd()}
                  placeholder="Add ticker — type symbol (e.g. AAPL)"
                  className="rounded-md border bg-background px-3 py-1.5 text-sm w-64 focus:outline-none focus:ring-1 focus:ring-ring font-mono"
                />
                <datalist id="ticker-symbols">
                  {allTickers
                    .filter(
                      (t) =>
                        addInput.length > 0 &&
                        (t.symbol.startsWith(addInput) ||
                          (t.name ?? "").toLowerCase().includes(addInput.toLowerCase()))
                    )
                    .slice(0, 10)
                    .map((t) => (
                      <option key={t.id} value={t.symbol}>
                        {t.name}
                      </option>
                    ))}
                </datalist>
                <button
                  onClick={handleAdd}
                  disabled={addStatus === "adding" || !addInput.trim()}
                  className="text-sm rounded-md bg-foreground text-background px-4 py-1.5 hover:opacity-90 disabled:opacity-50 transition-opacity"
                >
                  {addStatus === "adding" ? "Adding…" : "Add"}
                </button>
              </div>
              {addError && (
                <p className="mt-1.5 text-xs text-red-500">{addError}</p>
              )}
            </div>

            {/* Empty watchlist */}
            {activeWatchlist.items.length === 0 && rows.length === 0 && (
              <div className="rounded-lg border bg-card px-8 py-10 text-center text-muted-foreground text-sm">
                No tickers yet — add one above.
              </div>
            )}

            {/* Table */}
            {rows.length > 0 && (
              <div className="rounded-lg border overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/40">
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">
                        Symbol
                      </th>
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">
                        Name
                      </th>
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">
                        Price
                      </th>
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">
                        Day
                      </th>
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">
                        Next Catalyst
                      </th>
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">
                        Implied Move
                      </th>
                      <th className="py-2.5 px-4 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">
                        RV Rank
                      </th>
                      <th className="py-2.5 px-4" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <WatchlistRow
                        key={row.symbol}
                        row={row}
                        removing={removingIds.has(row.item.ticker_id)}
                        onRemove={() =>
                          handleRemove(row.item.ticker_id, row.symbol)
                        }
                      />
                    ))}
                  </tbody>
                </table>

                <div className="px-4 py-3 bg-muted/20 border-t border-border">
                  <p className="text-[11px] text-muted-foreground/60">
                    Prices via Finnhub — may be delayed up to 15 min. Implied move derived from near-term options straddle.
                    RV rank: where today&apos;s 20-day realized vol sits in its trailing 1-year range.
                  </p>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
