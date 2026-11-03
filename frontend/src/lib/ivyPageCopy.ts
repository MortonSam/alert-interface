// Every line the /ivy page adds (Sam, 2026-11-02): DRAFT, held for Sam's approval (backend/ops/reports/ivy_page_2026-11-02/wording.md).
// The ideas' titles and texts, the counts and their dates come from the API (/ivy-page); nothing here types a count or a date.
// No line has a colon or an em dash, and none tells anyone to buy or sell (lib/__tests__/ivyPage.test.ts).

export const IVY_PAGE = {
  headline: "Ivy reads the filings so you can understand the company, and shows her work.",
  searchLabel: "Walk through a stock with Ivy",
  searchPlaceholder: "Symbol or company name",
  length: (minutes: number) => `Seven steps, about ${minutes} minutes.`,
  quickPicks: "Or start with",
  noWalkthrough: (name: string) => `Ivy has no walkthrough for ${name} yet.`,
  cards: [
    { key: "walkthrough", title: "Walk through a stock",
      body: "Seven steps from the company's own filings. What it sells, whether it's growing, how much of each sale it keeps, how the stock has done, what it costs, what's coming up and what could go wrong." },
    { key: "read", title: "Ivy's Read",
      body: "On a stock's page, Ivy reads what the options market is pricing for the next report and sets it against the stock's own past report days." },
    { key: "ask", title: "Ask Ivy, with an account",
      body: "Ask a question about a stock. Ivy answers from the facts on file and shows the date of each one. Sign in to ask." },
  ],
  trustTitle: "Why you can trust her",
  trust: {
    notes: (n: string) => `${n} research notes, each checked against the company's filings by a second model before anyone reads it.`,
    confirmed: (n: string) => `${n} statements in those notes confirmed in the filings. A sentence the check can't confirm is taken out.`,
    walkthroughs: (n: string) => `${n} stocks with a walkthrough, each figure shown with its date.`,
  },
  asOf: (date: string) => `As of ${date}`,
  ideasTitle: "Seven ideas you can use on any stock",
  ideaLink: (name: string) => `See it on ${name}`,
  closing: "Ivy doesn't tell you what to buy or sell. She shows you how to decide for yourself.",
} as const;
