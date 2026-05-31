/**
 * Typed API client for the FastAPI backend.
 * All fetch calls go through /api/* which next.config.ts rewrites to :8000.
 */

const BASE = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

// ── Domain types (mirrors Pydantic schemas) ───────────────────────────────────

export type EventType = "earnings" | "macro" | "fda" | "ex_dividend" | "product_launch" | "other";
export type DataSource = "yfinance" | "edgar" | "fred" | "fda" | "polygon" | "manual";

export interface Ticker {
  id: string;
  symbol: string;
  name: string | null;
  sector: string | null;
  industry: string | null;
  exchange: string | null;
  market_cap: number | null;
  is_active: boolean;
  next_earnings_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface Event {
  id: string;
  ticker_id: string | null;
  event_type: EventType;
  event_date: string; // ISO date
  title: string;
  description: string | null;
  source: DataSource;
  source_url: string | null;
  is_confirmed: boolean;
  metadata_: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type EarningsOutcome = "beat" | "miss" | "meet" | "unknown";

export interface HistoricalReaction {
  id: string;
  ticker_id: string;
  event_id: string | null;
  event_type: EventType;
  event_date: string;
  close_before: string | null;
  open_after: string | null;
  close_after: string | null;
  pct_change_1d: string | null;
  pct_change_3d: string | null;
  pct_change_5d: string | null;
  volume_before: number | null;
  volume_after: number | null;
  notes: string | null;
  eps_estimate: string | null;
  eps_actual: string | null;
  revenue_estimate: number | null;
  revenue_actual: number | null;
  outcome: EarningsOutcome;
  created_at: string;
}

export interface WatchlistTicker {
  id: string;
  ticker_id: string;
  notes: string | null;
  added_at: string;
  ticker: Ticker;
}

export interface SourceFiling {
  form_type: string;
  accession_number: string;
  filing_date: string;
  url: string;
}

export interface VerificationClaim {
  claim: string;
  status: "supported" | "unsupported" | "contradicted";
  evidence: string;
}

export interface VerificationResult {
  claims: VerificationClaim[];
  summary: { supported: number; unsupported: number; contradicted: number };
}

export interface ResearchNote {
  id: string;
  ticker_id: string;
  generated_at: string;
  source_filings: SourceFiling[];
  content: string;
  model_used: string;
  input_tokens: number;
  output_tokens: number;
  verification: VerificationResult | null;
  verified_at: string | null;
  verification_model: string | null;
  created_at: string;
  updated_at: string;
}

export interface SparklinePoint {
  date: string;   // "YYYY-MM-DD"
  close: number;
}

export interface EarningsMarker {
  date: string;
  eps_estimate: number | null;
  eps_actual: number | null;
  outcome: "beat" | "miss" | "meet" | "unknown";
  pct_change_1d: number | null;
  pct_change_3d: number | null;
  pct_change_5d: number | null;
}

export interface TickerChart {
  symbol: string;
  period: string;
  history: SparklinePoint[];
  earnings_markers: EarningsMarker[];
  start_price: number | null;  // reference close for the period's change calculation
}

export interface TickerQuote {
  symbol: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  high: number | null;
  low: number | null;
  open: number | null;
  prev_close: number | null;
  timestamp: number | null;
  sparkline: SparklinePoint[];
}

export interface OptionContract {
  strike: number; bid: number | null; ask: number | null; last_price: number | null;
  volume: number | null; open_interest: number | null;
  implied_volatility: number | null;  // 0–1 decimal
  is_atm: boolean;
  data_quality_flag: string | null;   // null = trustworthy; else reason ("iv_outlier", "no_market", etc.)
}
export interface OptionsChain {
  symbol: string; expiration: string; current_price: number | null;
  calls: OptionContract[]; puts: OptionContract[];
  available_expirations: string[]; as_of: string;
}
export interface HistoricalMoveStats {
  avg_abs_move_pct: number; max_abs_move_pct: number; min_abs_move_pct: number;
  sample_size: number; above_expected: number; below_expected: number;
}
export interface ExpectedMove {
  symbol: string; current_price: number | null;
  expected_move_pct: number | null; expected_move_dollars: number | null;
  implied_range_low: number | null; implied_range_high: number | null;
  expiration_used: string | null; earnings_date: string | null;
  days_expiration_past_earnings: number | null;
  straddle_price: number | null; atm_strike: number | null;
  historical_stats: HistoricalMoveStats | null;
  plain_summary: string | null;
  data_quality_note: string | null; as_of: string;
}

export interface StrikeData {
  strike: number;
  call_mid: number | null;
  put_mid: number | null;
  call_iv: number | null;  // implied volatility 0–1 decimal, null if unavailable
  put_iv: number | null;
  is_atm: boolean;
}

export interface StrategyData {
  symbol: string;
  current_price: number | null;
  expiration: string | null;
  earnings_date: string | null;  // next earnings date for pre-expiry curve
  implied_range_low: number | null;
  implied_range_high: number | null;
  strikes: StrikeData[];
  as_of: string;
}

export interface OptionsRead {
  symbol: string;
  content: string;                        // 2–4 sentence interpretive prose
  facts: Record<string, string>;          // precomputed fact strings injected into the prompt
  model_used: string;
  generated_at: string;
  cached: boolean;
  as_of: string;
}

export interface RealizedVol {
  symbol: string;
  current_rv: number | null;       // annualized 20-day RV, 0–1 decimal (0.172 = 17.2%)
  rv_rank: number | null;          // 0–100: where today's RV sits in its 1-yr [min, max] range
  rv_percentile: number | null;    // 0–100: % of trailing 252 days with lower RV
  rv_min_1y: number | null;
  rv_max_1y: number | null;
  sample_days: number;
  window_days: number;
  as_of: string;
}

export interface SystemStatus {
  last_refreshed_at: string | null;
  total_tickers: number;
  total_reactions: number;
  most_recent_reaction_date: string | null;
}

export interface Watchlist {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  items: WatchlistTicker[];
}

// ── API methods ───────────────────────────────────────────────────────────────

export const api = {
  tickers: {
    list: (activeOnly = true) =>
      request<Ticker[]>(`/tickers/?active_only=${activeOnly}`),
    get: (id: string) => request<Ticker>(`/tickers/${id}`),
    quote: (symbol: string) => request<TickerQuote>(`/tickers/quote/${symbol}`),
    chart: (symbol: string, period = "1y") =>
      request<TickerChart>(`/tickers/chart/${symbol}?period=${period}`),
    create: (data: Partial<Ticker>) =>
      request<Ticker>("/tickers/", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: Partial<Ticker>) =>
      request<Ticker>(`/tickers/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/tickers/${id}`, { method: "DELETE" }),
    optionsRead: (symbol: string) =>
      request<OptionsRead>(`/tickers/options-read/${symbol}`),
    realizedVol: (symbol: string) =>
      request<RealizedVol>(`/tickers/rv/${symbol}`),
    expectedMove: (symbol: string) =>
      request<ExpectedMove>(`/tickers/expected-move/${symbol}`),
    strategyData: (symbol: string) =>
      request<StrategyData>(`/tickers/strategy-data/${symbol}`),
    options: (symbol: string, expiration?: string) =>
      request<OptionsChain>(expiration
        ? `/tickers/options/${symbol}?expiration=${encodeURIComponent(expiration)}`
        : `/tickers/options/${symbol}`),
  },

  watchlists: {
    list: () => request<Watchlist[]>("/watchlists/"),
    get: (id: string) => request<Watchlist>(`/watchlists/${id}`),
    create: (data: Pick<Watchlist, "name" | "description">) =>
      request<Watchlist>("/watchlists/", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: Partial<Watchlist>) =>
      request<Watchlist>(`/watchlists/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/watchlists/${id}`, { method: "DELETE" }),
    addTicker: (watchlistId: string, tickerId: string, notes?: string) =>
      request<Watchlist>(`/watchlists/${watchlistId}/tickers`, {
        method: "POST",
        body: JSON.stringify({ ticker_id: tickerId, notes }),
      }),
    removeTicker: (watchlistId: string, tickerId: string) =>
      request<void>(`/watchlists/${watchlistId}/tickers/${tickerId}`, { method: "DELETE" }),
  },

  events: {
    upcoming: (symbol?: string, days = 60, eventType?: EventType) => {
      const params = new URLSearchParams({ days: String(days) });
      if (symbol) params.set("symbol", symbol);
      if (eventType) params.set("event_type", eventType);
      return request<Event[]>(`/events/upcoming?${params}`);
    },
    list: (filters?: { ticker_id?: string; event_type?: EventType; from_date?: string; to_date?: string }) => {
      const params = new URLSearchParams(filters as Record<string, string>);
      return request<Event[]>(`/events/?${params}`);
    },
    get: (id: string) => request<Event>(`/events/${id}`),
    create: (data: Partial<Event>) =>
      request<Event>("/events/", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: Partial<Event>) =>
      request<Event>(`/events/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/events/${id}`, { method: "DELETE" }),
  },

  researchNotes: {
    get: (symbol: string) =>
      request<ResearchNote>(`/research-notes/?symbol=${encodeURIComponent(symbol)}`),
    generate: (symbol: string) =>
      request<ResearchNote>("/research-notes/generate", {
        method: "POST",
        body: JSON.stringify({ symbol }),
      }),
    verify: (symbol: string) =>
      request<ResearchNote>("/research-notes/verify", {
        method: "POST",
        body: JSON.stringify({ symbol }),
      }),
  },

  system: {
    status: () => request<SystemStatus>("/system/status"),
  },

  reactions: {
    list: (filters?: { symbol?: string; ticker_id?: string; event_type?: EventType }) => {
      const params = new URLSearchParams(
        Object.fromEntries(Object.entries(filters ?? {}).filter(([, v]) => v != null)) as Record<string, string>
      );
      return request<HistoricalReaction[]>(`/reactions/?${params}`);
    },
    get: (id: string) => request<HistoricalReaction>(`/reactions/${id}`),
    create: (data: Partial<HistoricalReaction>) =>
      request<HistoricalReaction>("/reactions/", { method: "POST", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/reactions/${id}`, { method: "DELETE" }),
  },
};
