// Every line the /ivy page adds (Sam, 2026-11-03: a demonstration, not a description), DRAFT, held for Sam's approval
// (backend/ops/reports/ivy_page_2026-11-02/wording.md). The step, the note sentence, the filing passage, the ideas' titles, the
// counts and their dates come from the API (/walkthrough/NVDA, /ivy-page); nothing here types a count or a date.
// No line has a colon or an em dash, and none tells anyone to buy or sell (lib/__tests__/ivyPage.test.ts).

export const IVY_PAGE = {
  headline: "Ivy reads the filings, so you understand the company.",
  searchLabel: "Walk through a stock with Ivy",
  searchPlaceholder: "Symbol or company name",
  quickPicks: "Or start with",
  noWalkthrough: (name: string) => `Ivy has no walkthrough for ${name} yet.`,
  stepFrom: (name: string) => `From Ivy's ${name} walkthrough`,
  startWalk: (name: string) => `Start the ${name} walkthrough`,
  checkTitle: "How she checks herself",
  noteFrom: (name: string) => `From Ivy's research note on ${name}`,
  filingFrom: (form: string, date: string) => `The ${form} filed ${date}`,
  readFiling: "Read it in the filing",
  checked: (n: string, date: string) => `${n} statements in Ivy's research notes checked against the filings, as of ${date}.`,
  ideasTitle: "Seven ideas you can use on any stock",
  closing: "Ivy doesn't tell you what to buy or sell. She shows you how to decide for yourself.",
} as const;
