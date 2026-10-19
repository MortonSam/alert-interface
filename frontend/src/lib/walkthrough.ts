/**
 * Ivy's walkthrough: the types the API serves (backend routers/walkthrough, services/walkthrough), the fetchers, and the
 * concepts a visitor has learned, kept in this browser only (localStorage, no account).
 *
 * Every sentence and number arrives built by the backend; this module adds no figure and no wording of its own beyond the
 * known-concept line, which also comes from the API (known_concept_line).
 */

export interface WalkNumber { label: string; value: string; as_of: string }
export interface WalkCheck { concept: string; question: string; options: string[]; answer: number; why: string }
export interface WalkIdea { concept: string; title: string; text: string }
export interface ChartSeries { key: "stock" | "spy" | "sector"; label: string; points: [string, number][] }
export interface PriceChart { kind: "price_vs_market"; as_of: string; start: string; series: ChartSeries[] }
export interface PeChart { kind: "pe_range"; as_of: string; points: [string, number][]; median: number; today: number; sector_median: number | null; sector: string | null }

export interface WalkStep {
  n: number;
  key: "business" | "growth" | "margins" | "stock" | "valuation" | "upcoming" | "risks";
  question: string;
  status: "ok" | "partial" | "absent";
  absent: string | null;
  numbers: WalkNumber[];
  sentences: string[];
  story: string | null;
  idea: WalkIdea | null;
  chart: PriceChart | PeChart | null;
  check: WalkCheck | null;
  deeper: WalkNumber[];
  source: { label: string; url: string | null } | null;
  summary: string | null;
  uncertain: string | null;
  risks?: { n: number; sentence: string }[];
}

export interface CompareCell { value: string; as_of: string; measure?: string }
export interface CompareSide { symbol: string; name: string; rows: Record<string, CompareCell | null> }
export interface CompareChoice { kind: "rival" | "ruler"; symbol: string; name: string; basis?: string; rule?: string }

export interface Walkthrough {
  version: number;
  symbol: string;
  name: string;
  sector: string | null;
  minutes: number;
  as_of: string;
  steps: WalkStep[];
  summary: { known: { n: number; line: string; shown: boolean }[]; uncertain: string[]; concepts: { concept: string; title: string }[]; closing: string };
  compare: CompareSide;
  known_concept_line: string;
  compare_choices: CompareChoice[];
  ask_enabled: boolean;
}

export interface CompareResult {
  a: CompareSide;
  b: CompareSide;
  rows: { key: string; label: string }[];
  missing: string;
  story: string | null;
  idea: WalkIdea;
}

export interface Featured { symbol: string | null; name: string | null; rule: string | null; date: string | null; minutes?: number }

async function getJson<T>(path: string): Promise<T | null> {
  try {
    // the admin token (a browser with preview on) sees the walkthrough while IVY_WALKTHROUGH_ENABLED is off
    let token: string | null = null;
    try { token = window.localStorage.getItem("admin_token"); } catch { /* private mode */ }
    const res = await fetch(`/api/v1${path}`, token ? { headers: { "X-Admin-Token": token } } : undefined);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export const fetchWalkthrough = (symbol: string) => getJson<Walkthrough>(`/walkthrough/${encodeURIComponent(symbol.toUpperCase())}`);
export const fetchCompare = (a: string, b: string) =>
  getJson<CompareResult>(`/walkthrough/compare?a=${encodeURIComponent(a.toUpperCase())}&b=${encodeURIComponent(b.toUpperCase())}`);
export const fetchFeatured = () => getJson<Featured>("/walkthrough-featured");

/** "New to Micron Technology? Walk through it with Ivy, about 3 minutes." */
export function entryLine(name: string, minutes: number): { lead: string; action: string } {
  return { lead: `New to ${name}?`, action: `Walk through it with Ivy, about ${minutes} minutes.` };
}

export const HOME_ENTRY = (minutes: number) => `Learn to read a stock in ${minutes} minutes`;

// ── concepts learned, in this browser only ──────────────────────────────────────────────────────────────────────────────

const STORE_KEY = "ivy_concepts_v1";
export interface Learned { [concept: string]: { symbol: string; name: string; at: string } }

export function readLearned(): Learned {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORE_KEY);
    return raw ? (JSON.parse(raw) as Learned) : {};
  } catch {
    return {};
  }
}

/** Record a concept the first time it is learned; a concept keeps the stock it was first learned on. */
export function learn(concept: string, symbol: string, name: string, now = new Date()): Learned {
  const cur = readLearned();
  if (!cur[concept]) {
    cur[concept] = { symbol, name, at: now.toISOString() };
    try {
      window.localStorage.setItem(STORE_KEY, JSON.stringify(cur));
    } catch {
      /* private mode: the walkthrough still works, it just won't remember */
    }
  }
  return cur;
}

/** The short "The idea" line for a concept learned on another stock, or null (learned on this stock, or never). */
export function knownLine(template: string, idea: WalkIdea, learned: Learned, symbol: string, name: string): string | null {
  const l = learned[idea.concept];
  if (!l || l.symbol === symbol) return null;
  return template.replace("{title}", idea.title).replace("{learned_from}", l.name).replace("{name}", name);
}
