/** Source scan for the rule "every displayed value carries its own date or an absence reason", over the four pages.
 * Each rule names a file, a forbidden pattern, and what the page must use instead. The test fails on any finding;
 * `scanDisplayedDates` also serves to list findings on an older tree. */

export interface DateRule { file: string; forbid: RegExp; because: string }

export const DATE_RULES: DateRule[] = [
  { file: "components/QuestionStrip.tsx", forbid: /new Date\(|Date\.now\(|toLocaleDateString\(\)|last_refreshed_at/, because: "an answer's date comes from its data, never from the request time" },
  { file: "components/AskIvy.tsx", forbid: /new Date\(|Date\.now\(|toLocaleDateString\(\)|last_refreshed_at|\blive\b|real-time|right now/i, because: "Ivy's answer is dated by its facts, never by the request time, and is never called live" },
  { file: "components/Briefing.tsx", forbid: /new Date\(|Date\.now\(|toLocaleDateString\(\)|last_refreshed_at/, because: "a briefing date comes from its sentence or input, never from the request time" },
  { file: "app/tickers/[symbol]/page.tsx", forbid: /today&apos;s range|today's range/, because: "the band is labelled by the chain date" },
  { file: "app/tickers/[symbol]/page.tsx", forbid: /as of \{fmtQuoteTime\(/, because: "a quote shows its date and time (fmtQuoteDateTime)" },
  { file: "app/tickers/[symbol]/page.tsx", forbid: /"1d": "today"/, because: "the 1d change is since the prior close, not necessarily today" },
  { file: "app/tickers/[symbol]/page.tsx", forbid: /Data as of \{timeAgo\(health\.last_refreshed_at\)\}/, because: "freshness comes from the dataset ages" },
  { file: "app/discover/page.tsx", forbid: /Quotes as of \{fmtQuoteTime\(/, because: "a quote shows its date and time" },
  { file: "app/discover/page.tsx", forbid: /health\.last_refreshed_at/, because: "freshness comes from the dataset ages" },
  { file: "app/discover/page.tsx", forbid: /fmtPrice\(quotes\.get\(([a-zA-Z.]+)\)!\.price\) : undefined\}\n(?!\s*priceAsOf=)/, because: "a row price carries priceAsOf" },
  { file: "lib/discoverSentences.ts", forbid: /now \$\{fmtPrice\(pick\.current_price\)\}(?![\s\S]{0,400}price_as_of)/, because: "the ledger price is dated by its last trade" },
  { file: "components/DiscoverRow.tsx", forbid: /\{price && <span/, because: "a price renders only with its as-of" },
  { file: "app/build/page.tsx", forbid: /"n\/a"/, because: "an absent fact says why: absent: <reason>" },
  { file: "app/build/page.tsx", forbid: /updated once a day/, because: "the options cadence comes from the cadence record" },
  // "Terminals cost thirty grand a year" is the challenge headline, kept verbatim at Sam's instruction (2026-10-05): a line about
  // the market, not a figure from this system's data. Every other typed figure on the page stays forbidden.
  { file: "app/page.tsx", forbid: /Thirty million/, because: "no unsourced figure" },
];

export const DATE_REQUIREMENTS: { file: string; require: RegExp; because: string }[] = [
  { file: "components/QuestionStrip.tsx", require: /asOfLabel\(q\.as_of, q\.as_of_kind\)/, because: "every answer shows when its fact was known, worded by kind, never a date ahead" },
  { file: "components/QuestionStrip.tsx", require: /answerParts\(q\.data, q\.inputs\)/, because: "every number in an answer carries its receipt from the API's inputs" },
  { file: "components/Briefing.tsx", require: /sentenceReceipt\(s\)/, because: "every briefing sentence shows how it was computed and its own as-of date, from the API" },
  { file: "components/Briefing.tsx", require: /sourceLine\(inp\)/, because: "every input is listed with its own date and source" },
  { file: "app/tickers/[symbol]/page.tsx", require: /Last bar \{chartLastBar\}/, because: "the chart names its last bar" },
  { file: "app/tickers/[symbol]/page.tsx", require: /putCall\.snapshot_date/, because: "the put/call ratio shows its snapshot date" },
  { file: "app/tickers/[symbol]/page.tsx", require: /realizedVol\?\.as_of/, because: "RV and RV rank show their snapshot date" },
  { file: "app/tickers/[symbol]/page.tsx", require: /magnitude_trend_as_of/, because: "the magnitude trend shows its snapshot date" },
  { file: "app/discover/page.tsx", require: /priceAsOf=\{quoteAsOf\(/, because: "every Discover price carries its as-of" },
  { file: "app/build/page.tsx", require: /absentCell\(fb, "atm_iv_pct"/, because: "the fact grid gives a reason for an absent ATM IV" },
];

export function scanDisplayedDates(read: (file: string) => string): string[] {
  const out: string[] = [];
  for (const r of DATE_RULES) {
    const src = read(r.file);
    const m = src.match(r.forbid);
    if (m) out.push(`${r.file}: found ${JSON.stringify(m[0].slice(0, 60))}; ${r.because}`);
  }
  for (const r of DATE_REQUIREMENTS) {
    if (!r.require.test(read(r.file))) out.push(`${r.file}: missing ${r.require}; ${r.because}`);
  }
  return out;
}
