// Every visible string the walkthrough's frame adds (labels, buttons, headings). The step content itself comes from the API.
// Listed verbatim in backend/ops/reports/wording_ivy_walkthrough_2026-10-19.md; a test holds them free of colons and em dashes.

/** A company's possessive: "NVIDIA's", "Ross Stores'", "Lowe's" (a name already ending in 's keeps it). */
export function possessive(name: string): string {
  if (/'s$/i.test(name)) return name;
  return /s$/i.test(name) ? `${name}'` : `${name}'s`;
}

export const WALK_COPY = {
  ivy: "Ivy",
  stepOf: (n: number, total: number) => `Step ${n} of ${total}`,
  // each step's short name, shown above its question (Sam, 2026-11-04)
  stepLabel: { business: "Overview", growth: "Growth", margins: "Margin", stock: "Historical", valuation: "Valuation", upcoming: "Earnings", risks: "Risks" },
  back: "Back",
  next: "Next",
  toSummary: "See the summary",
  close: "Close",
  idea: "The idea",
  quickCheck: "Quick check",
  skip: "Skip",
  right: "Right.",
  notQuite: "Not quite.",
  goDeeper: "Go deeper",
  readFiling: "Read it in the filing",
  notShownBadge: "Not shown yet",
  summaryTitle: (name: string) => `What you now know about ${name}`,
  uncertainTitle: "What's still uncertain",
  conceptsTitle: "Ideas you can use on any stock",
  compareMove: (name: string) => `Compare ${name}`,
  askMove: "Ask Ivy a question",
  fullPageMove: "See the full page",
  compareTitle: "Compare side by side",
  rivalChoice: (name: string, label?: string) => `${name}, ${label ?? "another company in its industry"}`,
  rulerChoice: (name: string) => `${name}, a company you know`,
  // an idea met on an earlier walkthrough (Sam, 2026-11-10: "You know Where the money comes from from NVIDIA"): the idea's own
  // title leads, so its capital and its last word stay as written
  // a small label above the idea's title when the visitor met it on another stock (Sam, 2026-11-10)
  knownFrom: (from: string) => `You saw this idea in ${possessive(from)} walkthrough`,
  searchPrompt: "Or pick any S&P 500 stock",
  searchPlaceholder: "Symbol or company name",
  noWalkthrough: (name: string) => `Ivy has no walkthrough for ${name} yet.`,
  backToSummary: "Back to the summary",
  loading: "Loading",
  unavailable: "Ivy's walkthrough isn't available right now.",
} as const;
