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
  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
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
  // Computed enrichment field (populated server-side, null for non-earnings rows)
  eps_surprise_pct: number | null;  // (eps_actual − eps_estimate) / |eps_estimate| × 100
  // gap_pct / intraday_pct omitted: open_after/close_after are event-day pre-print prices for
  // after-close reporters, so those figures measure pre-earnings trading, not the reaction.
  // Revisit when next-day OHLCV (T+1 open) is stored.
}

export interface ReactionSummary {
  symbol: string;
  sector: string | null;
  total_quarters: number;
  beat_count: number;
  miss_count: number;
  meet_count: number;
  beat_rate_pct: number;
  beat_but_dropped_count: number;
  beat_but_dropped_rate_pct: number | null;
  avg_1d_on_beat: number | null;
  avg_1d_on_miss: number | null;
  avg_abs_1d: number | null;
  sector_avg_abs_1d: number | null;
  sector_peer_count: number;
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

export interface StructuredNoteItem {
  lead: string;
  detail: string;
}

export interface StructuredNoteStats {
  market_cap: number | null;
  eps_estimate: number | null;
  eps_actual: number | null;
  eps_beat_pct: number | null;
  revenue_estimate: number | null;
  revenue_actual: number | null;
  revenue_beat_pct: number | null;
  beat_count: number | null;
  total_quarters: number | null;
  latest_move_1d: string | null;
  latest_outcome: "beat" | "miss" | "meet" | null;
  latest_quarter_date: string | null;
}

export interface StructuredNoteFinancials {
  forward_pe: number | null;
  pe_ttm: number | null;
  ps_ttm: number | null;
  peg_ttm: number | null;
  forward_peg: number | null;
  gross_margin_ttm: number | null;
  gross_margin_5y: number | null;
  operating_margin_ttm: number | null;
  operating_margin_5y: number | null;
  net_margin_ttm: number | null;
  net_margin_5y: number | null;
  revenue_growth_ttm: number | null;
  eps_growth_ttm: number | null;
  roe_ttm: number | null;
}

export interface StructuredNote {
  rating: "bullish" | "neutral" | "bearish";
  bottom_line: string;
  what_they_do: string;
  highlights: StructuredNoteItem[];
  watch: StructuredNoteItem[];
  risks: StructuredNoteItem[];
  stats: StructuredNoteStats;
  financials: StructuredNoteFinancials | null;
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
  structured_content: StructuredNote | null;
  verification: VerificationResult | null;
  verified_at: string | null;
  verification_model: string | null;
  status: "generating" | "verifying" | "complete" | "failed";
  error: string | null;
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

export interface BatchQuote {
  symbol: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
}

export interface NewsItem {
  headline: string;
  source: string;
  url: string;
  datetime: number;   // unix seconds
  summary: string;
}

export interface NewsResponse {
  items: NewsItem[];
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

// ── Discover types ───────────────────────────────────────────────────────────

export interface ReportingSoonItem {
  symbol: string;
  name: string | null;
  earnings_date: string;
  is_confirmed: boolean;
}

export interface ReportingSoonResponse {
  items: ReportingSoonItem[];
  total: number;
}

export interface JustReportedItem {
  symbol: string;
  name: string | null;
  event_date: string;
  pct_change_1d: number | null;
  outcome: EarningsOutcome;
}

export interface JustReportedResponse {
  items: JustReportedItem[];
  total: number;
}

export interface SuggestionItem {
  symbol: string;
  name: string | null;
  score: number;
  reports_in_days: number | null;
  recent_move_pct: number | null;
  recent_move_5d: number | null;
  recent_outcome: EarningsOutcome | null;
  event_date: string | null;  // ISO date of the reaction's report
}

export interface SuggestionsResponse {
  items: SuggestionItem[];
}

export interface BatchEnrichItem {
  symbol: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  expected_move_pct: number | null;
  earnings_date: string | null;
  rv_rank: number | null;
  current_rv: number | null;
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

export type ThesisDirection = "bullish" | "bearish" | "neutral";
export type ThesisStatus = "open" | "resolved" | "needs_manual_resolution";
export type SelfGrade = "right" | "right_for_wrong_reasons" | "wrong";

export interface Thesis {
  id: string;
  ticker_id: string;
  ticker_symbol: string | null;
  direction: ThesisDirection;
  conviction: number;          // 1–5
  catalyst: string | null;
  price_target: string | null; // Decimal as string from backend
  target_date: string;         // "YYYY-MM-DD"
  entry_price: string | null;  // stock price captured at creation
  reasoning: string | null;
  notes: string | null;
  status: ThesisStatus;
  resolved_at: string | null;
  price_at_resolution: string | null;
  direction_correct: boolean | null;
  target_reached: boolean | null;
  self_grade: SelfGrade | null;
  reflection: string | null;
  // Option leg
  option_type: string | null;           // "call" | "put"
  strike: string | null;                // Decimal as string
  option_expiration: string | null;     // "YYYY-MM-DD"
  entry_premium: string | null;         // option mid at creation, server-captured
  contracts: number;
  strike2: string | null;               // second leg (spread)
  entry_premium2: string | null;
  spread_type: string | null;
  from_ai_draft: boolean;
  // Option P&L (filled at resolution)
  option_pnl_dollars: string | null;
  option_pnl_pct: string | null;
  created_at: string;
  updated_at: string;
  is_due: boolean;
}

export interface ThesisMarkRead {
  thesis_id: string;
  option_type: string | null;
  strike: number | null;
  strike2: number | null;
  current_price: number | null;
  current_mid1: number | null;
  current_mid2: number | null;
  entry_premium: number | null;
  entry_premium2: number | null;
  contracts: number;
  pnl_dollars: number | null;
  pnl_pct: number | null;                // fraction: 0.28 = +28%
  mark_basis: "live_chain" | "intrinsic" | "not_found" | "no_option_leg";
  is_expired: boolean;
  mark_note: string | null;
  as_of: string;
}

export interface ThesisCreate {
  symbol: string;
  direction: ThesisDirection;
  conviction: number;
  catalyst?: string;
  price_target?: number;
  target_date: string;
  reasoning?: string;
  notes?: string;
  // Option leg (entry_premium captured server-side from chain)
  option_type?: "call" | "put";
  strike?: number;
  option_expiration?: string;   // "YYYY-MM-DD"
  contracts?: number;
  strike2?: number;
  spread_type?: string;
  from_ai_draft?: boolean;
}

export interface ThesisResolve {
  reflection: string;
  self_grade: SelfGrade;
  price_override?: number;
}

export interface ThesisDraftRequest {
  symbol: string;
  direction: ThesisDirection;
  aggressiveness: "conservative" | "moderate" | "aggressive";
  proposed_target?: number;
}

export interface ThesisDraftStrike {
  strike: number;
  mid: number;
  iv: number | null;
}

export interface ThesisDraftRead {
  symbol: string;
  direction: ThesisDirection;
  aggressiveness: string;
  suggested_target: number | null;
  suggested_strike: number | null;
  suggested_spread_strike: number | null;
  strategy: string | null;
  reasoning: string;
  realism_flag: string | null;
  fact_block: {
    current_price: number;
    atm_strike: number | null;
    earnings_date: string | null;
    expiration_used: string | null;
    days_to_expiration: number | null;
    expected_move_pct: number | null;      // percentage, e.g. 4.7
    expected_move_dollars: number | null;
    implied_range_low: number | null;
    implied_range_high: number | null;
    hist_avg_abs_move_pct: number | null;  // percentage, e.g. 2.74
    hist_max_abs_move_pct: number | null;
    hist_sample_size: number;
    beat_rate_pct: number | null;
    beat_but_dropped_rate_pct: number | null;
    atm_iv_pct: number | null;
    rv_20d_pct: number | null;
    rv_rank: number | null;
    iv_rv_spread_pp: number | null;
    primary_strikes: ThesisDraftStrike[];
    secondary_strikes: ThesisDraftStrike[];
    [key: string]: unknown;
  };
  model_used: string;
  generated_at: string;
}

export interface ThesisDraftAlternativeRequest {
  symbol: string;
  direction: ThesisDirection;
  aggressiveness: "conservative" | "moderate" | "aggressive";
  budget: number;
  best_strike: number;
  best_spread_strike?: number | null;
  best_cost: number;
}

export interface ThesisDraftAlternativeRead {
  fits: boolean;
  strategy: string | null;
  suggested_strike: number | null;
  suggested_spread_strike: number | null;
  cost_to_enter: number | null;
  target: number | null;
  tradeoff: string | null;
  reasoning: string | null;
  note: string | null;
  model_used: string;
  generated_at: string;
}

export interface ThesisStockMarkRead {
  /** Live price mark for a stock-only thesis (no option leg). */
  thesis_id: string;
  current_price: number | null;
  entry_price: number | null;
  price_target: number | null;
  pct_from_entry: number | null;   // signed %, e.g. +0.96 or -2.1
  pct_to_target: number | null;    // 0–100+ (% of the way to target; can exceed 100)
  verdict: "on_track" | "reversed" | "target_hit" | null;
  direction: string;
  as_of: string;
  auto_resolved: boolean;
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
    quotes: (symbols: string[]) =>
      request<BatchQuote[]>(`/tickers/quotes?symbols=${symbols.join(",")}`),
    batchEnrich: (symbols: string[]) =>
      request<BatchEnrichItem[]>(`/tickers/batch-enrich?symbols=${symbols.join(",")}`),
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
    news: (symbol: string) =>
      request<NewsResponse>(`/tickers/${symbol}/news`),
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

  theses: {
    list: (filters?: { symbol?: string; status?: string }) => {
      const params = new URLSearchParams(
        Object.fromEntries(Object.entries(filters ?? {}).filter(([, v]) => v != null)) as Record<string, string>
      );
      return request<Thesis[]>(`/theses/?${params}`);
    },
    get: (id: string) => request<Thesis>(`/theses/${id}`),
    create: (data: ThesisCreate) =>
      request<Thesis>("/theses/", { method: "POST", body: JSON.stringify(data) }),
    resolve: (id: string, data: ThesisResolve) =>
      request<Thesis>(`/theses/${id}/resolve`, { method: "POST", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/theses/${id}`, { method: "DELETE" }),
    draft: (data: ThesisDraftRequest) =>
      request<ThesisDraftRead>("/theses/draft", { method: "POST", body: JSON.stringify(data) }),
    draftAlternative: (data: ThesisDraftAlternativeRequest) =>
      request<ThesisDraftAlternativeRead>("/theses/draft-alternative", { method: "POST", body: JSON.stringify(data) }),
    mark: (id: string) =>
      request<ThesisMarkRead>(`/theses/${id}/mark`),
    stockMark: (id: string) =>
      request<ThesisStockMarkRead>(`/theses/${id}/stock-mark`),
  },

  discover: {
    reportingSoon: (days = 7, limit = 12) =>
      request<ReportingSoonResponse>(`/discover/reporting-soon?days=${days}&limit=${limit}`),
    justReported: (days = 5, limit = 12) =>
      request<JustReportedResponse>(`/discover/just-reported?days=${days}&limit=${limit}`),
    suggestions: (limit = 5) =>
      request<SuggestionsResponse>(`/discover/suggestions?limit=${limit}`),
  },

  reactions: {
    list: (filters?: { symbol?: string; ticker_id?: string; event_type?: EventType }) => {
      const params = new URLSearchParams(
        Object.fromEntries(Object.entries(filters ?? {}).filter(([, v]) => v != null)) as Record<string, string>
      );
      return request<HistoricalReaction[]>(`/reactions/?${params}`);
    },
    summary: (symbol: string) =>
      request<ReactionSummary>(`/reactions/summary?symbol=${encodeURIComponent(symbol)}`),
    get: (id: string) => request<HistoricalReaction>(`/reactions/${id}`),
    create: (data: Partial<HistoricalReaction>) =>
      request<HistoricalReaction>("/reactions/", { method: "POST", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/reactions/${id}`, { method: "DELETE" }),
  },
};
