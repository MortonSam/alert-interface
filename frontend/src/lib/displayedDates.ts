/** Source scan for the rule "every displayed value carries its own date or an absence reason", over the four pages.
 * Each rule names a file, a forbidden pattern, and what the page must use instead. The test fails on any finding;
 * `scanDisplayedDates` also serves to list findings on an older tree. */

export interface DateRule { file: string; forbid: RegExp; because: string }

export const DATE_RULES: DateRule[] = [
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
  { file: "app/page.tsx", forbid: /thirty grand|Thirty million/, because: "no unsourced figure" },
];

export const DATE_REQUIREMENTS: { file: string; require: RegExp; because: string }[] = [
  { file: "app/tickers/[symbol]/page.tsx", require: /Last bar \{chartLastBar\}/, because: "the chart names its last bar" },
  { file: "app/tickers/[symbol]/page.tsx", require: /putCall\.snapshot_date/, because: "the put/call ratio shows its snapshot date" },
  { file: "app/tickers/[symbol]/page.tsx", require: /realizedVol\?\.as_of/, because: "RV and RV rank show their snapshot date" },
  { file: "app/tickers/[symbol]/page.tsx", require: /magnitude_trend_as_of/, because: "the magnitude trend shows its snapshot date" },
  { file: "app/discover/page.tsx", require: /priceAsOf=\{fmtQuoteDateTime\(/, because: "every Discover price carries its as-of" },
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
