import type { SiteStats } from "@/lib/api";

/**
 * The homepage counters never lose their screen to a slow, restarting or erroring backend. Three layers, in order:
 *  1. server: the page fetches /system/stats at render with a STATS_REVALIDATE_SECONDS revalidation; a revalidation that fails
 *     throws, so Next keeps serving the last good page (the counts it last rendered, each with its own as-of date);
 *  2. stored: the browser keeps the last counts it received (SNAPSHOT_KEY), shown while a refresh is in flight or has failed;
 *  3. fresh: a client refresh replaces either when it succeeds and never when it fails.
 * With no layer at all (a first visit while the backend is down and no server counts), the row still renders with its four
 * labels and a dash for each count, titled with why.
 */
export const STATS_REVALIDATE_SECONDS = 300;
export const SNAPSHOT_KEY = "site_stats_snapshot_v1";
export const UNAVAILABLE_TITLE = "Counts not available right now: the data service could not be reached";

export interface StatsSnapshot {
  stats: SiteStats;
  fetched_at: string;     // ISO, the browser's clock when the counts arrived
}

export type StatsSource = "fresh" | "server" | "stored" | null;

const KEYS: Array<keyof SiteStats> = ["option_contracts_captured", "licensed_daily_prices", "earnings_reports_measured", "analyst_reactions_measured"];

export function isSiteStats(x: unknown): x is SiteStats {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return KEYS.every((k) => typeof o[k] === "number" && Number.isFinite(o[k] as number));
}

/** Pure: the counts to show and where they came from, fresh over server over stored. */
export function pickStats(fresh: SiteStats | null, server: SiteStats | null, stored: StatsSnapshot | null): { stats: SiteStats | null; source: StatsSource } {
  if (fresh) return { stats: fresh, source: "fresh" };
  if (server) return { stats: server, source: "server" };
  if (stored) return { stats: stored.stats, source: "stored" };
  return { stats: null, source: null };
}

type StorageLike = Pick<Storage, "getItem" | "setItem">;

/** The last counts this browser received, or null when none, unreadable or malformed. Never throws. */
export function readSnapshot(storage: StorageLike | null | undefined): StatsSnapshot | null {
  try {
    const raw = storage?.getItem(SNAPSHOT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StatsSnapshot>;
    return parsed && isSiteStats(parsed.stats) && typeof parsed.fetched_at === "string" ? { stats: parsed.stats, fetched_at: parsed.fetched_at } : null;
  } catch {
    return null;
  }
}

/** Keep counts that arrived. Never throws (private windows, blocked storage). */
export function writeSnapshot(storage: StorageLike | null | undefined, stats: SiteStats, now: Date = new Date()): void {
  try {
    storage?.setItem(SNAPSHOT_KEY, JSON.stringify({ stats, fetched_at: now.toISOString() } satisfies StatsSnapshot));
  } catch {
    /* storage unavailable: the server and fresh layers still serve */
  }
}

export function browserStorage(): StorageLike | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

/** Server only: the counts for the page render. On failure it throws, except during a production build, where a backend that
 * cannot be reached ships the page without server counts (the stored and fresh layers still serve) rather than failing the build. */
export async function fetchSiteStatsServer(): Promise<SiteStats | null> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";
  try {
    const res = await fetch(`${base}/v1/system/stats`, { next: { revalidate: STATS_REVALIDATE_SECONDS } });
    if (!res.ok) throw new Error(`site stats: HTTP ${res.status}`);
    const body: unknown = await res.json();
    if (!isSiteStats(body)) throw new Error("site stats: unexpected body");
    return body;
  } catch (err) {
    if (process.env.NEXT_PHASE === "phase-production-build") return null;
    throw err;      // a failed revalidation keeps the last good page serving
  }
}
