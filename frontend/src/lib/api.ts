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

export interface ResearchNote {
  id: string;
  ticker_id: string;
  generated_at: string;
  source_filings: SourceFiling[];
  content: string;
  model_used: string;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
  updated_at: string;
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
    create: (data: Partial<Ticker>) =>
      request<Ticker>("/tickers/", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: Partial<Ticker>) =>
      request<Ticker>(`/tickers/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/tickers/${id}`, { method: "DELETE" }),
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
