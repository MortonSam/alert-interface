/**
 * Ivy's walkthrough: the types the API serves (backend routers/walkthrough, services/walkthrough), the fetchers, and the
 * concepts a visitor has learned, kept in this browser only (localStorage, no account).
 *
 * Every sentence and number arrives built by the backend; this module adds no figure of its own. Once a concept is known from
 * another stock, "The idea" becomes one line comparing the two stocks on it, each half the `fact` its own walkthrough serves
 * (compareLine), so both figures come from the API with their periods; with either missing, the full idea shows.
 */

export interface WalkNumber { label: string; value: string; as_of: string }
/** same_answer: set when the right answer is the same text for every stock that reaches it (step 6; step 2 by direction). */
export interface WalkCheck { concept: string; question: string; options: string[]; answer: number; why: string; same_answer?: string }
export interface WalkIdea { concept: string; title: string; text: string }
export interface ChartSeries { key: "stock" | "spy" | "sector"; label: string; points: [string, number][] }
export interface PriceChart { kind: "price_vs_market"; as_of: string; start: string; series: ChartSeries[] }
/** This stock's figure for its step's concept, for the line comparing two stocks once the concept is known. */
export interface WalkFact { concept: string; measure: string; lead: string; short: string; tail: string }
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
  gap: string | null;
  fact: WalkFact | null;
  risks?: { n: number; sentence: string }[];
}

export interface CompareCell { value: string; as_of: string }
export interface CompareSide { symbol: string; name: string; reit?: boolean; rows: Record<string, CompareCell | null> }
export interface CompareChoice { kind: "rival" | "ruler"; symbol: string; name: string; basis?: string; label?: string; rule?: string }

export interface Walkthrough {
  version: number;
  symbol: string;
  name: string;
  sector: string | null;
  reit?: boolean;
  minutes: number;
  as_of: string;
  steps: WalkStep[];
  summary: { known: { n: number; line: string; shown: boolean }[]; uncertain: string[]; concepts: { concept: string; title: string }[]; closing: string };
  compare: CompareSide;
  compare_choices: CompareChoice[];
  ask_enabled: boolean;
  /** Whether a ticker page offers this walkthrough: enough of its steps show data (the backend's ENTRY_MIN_STEPS). */
  entry: boolean;
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
/** Per concept: the stock it was first learned on, and the last check answer met for it (WalkCheck.same_answer). */
export interface Learned { [concept: string]: { symbol: string; name: string; at: string; last?: string } }

export function readLearned(): Learned {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORE_KEY);
    return raw ? (JSON.parse(raw) as Learned) : {};
  } catch {
    return {};
  }
}

/** Record a concept the first time it is learned (it keeps the stock it was first learned on), and the last same-answer check met. */
export function learn(concept: string, symbol: string, name: string, now = new Date(), met?: string): Learned {
  const cur = readLearned();
  const first = !cur[concept];
  if (first) cur[concept] = { symbol, name, at: now.toISOString() };
  if (met) cur[concept] = { ...cur[concept], last: met };
  if (first || met) {
    try {
      window.localStorage.setItem(STORE_KEY, JSON.stringify(cur));
    } catch {
      /* private mode: the walkthrough still works, it just won't remember */
    }
  }
  return cur;
}

/** The stock a concept was first learned on, when that is another stock (else null: learned here, or never). */
export function learnedElsewhere(idea: WalkIdea | null, learned: Learned, symbol: string): { symbol: string; name: string } | null {
  const l = idea ? learned[idea.concept] : undefined;
  return l && l.symbol !== symbol ? { symbol: l.symbol, name: l.name } : null;
}

/** The fact a walkthrough serves for a concept (from a shown step), or null. */
export function factFor(w: Walkthrough | null, concept: string): WalkFact | null {
  const s = w?.steps.find((x) => x.status !== "absent" && x.fact?.concept === concept);
  return s?.fact ?? null;
}

/**
 * One line comparing the stock a concept was learned on with this one, both figures on the same measure:
 * "Micron Technology's sales grew 379.3% from a year earlier in fiscal Q4 2026. Realty Income's grew 9.7% in Q2 2026."
 * Null (show the full idea) when either figure is missing or the two are different measures (a gross margin and an operating one).
 */
export function compareLine(other: WalkFact | null, mine: WalkFact | null): string | null {
  if (!other || !mine || other.concept !== mine.concept || other.measure !== mine.measure) return null;
  const tail = mine.tail === other.tail || !mine.tail ? "" : ` ${mine.tail}`;
  return `${other.lead}${other.tail ? ` ${other.tail}` : ""}. ${mine.short}${tail}.`;
}

/** A check whose right answer the visitor has already met for this concept (its last one): shown only the first time. */
export function alreadyMet(check: WalkCheck | null, learned: Learned): boolean {
  return !!check?.same_answer && learned[check.concept]?.last === check.same_answer;
}
