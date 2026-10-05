import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

describe("home page claims the disclosures support (audit items 8, 9, 21)", () => {
  it("the note block is the latest verified note from the API, never a sample, and says so when there is none", async () => {
    const home = read("app/page.tsx");
    expect(home).toContain("<LatestVerifiedNote />");
    expect(home).toContain("The latest verified note");
    expect(home).not.toMatch(/NotePreview|Illustration|Sample note|Generated &amp; verified|4\.30T|18\/20|\$26\.3B/);
    const block = read("components/LatestVerifiedNote.tsx");
    expect(block).toContain("api.researchNotes.latestVerified()");
    expect(block).toContain("href={`/tickers/${note.symbol}`}");
    expect(block).not.toMatch(/\$[0-9]/);   // no typed dollar figure in the markup
    const { NO_VERIFIED_NOTE, noteFacts, verificationLine } = await import("@/lib/latestNote");
    expect(NO_VERIFIED_NOTE).toContain("No verified research note is available right now");
    const facts = noteFacts({ market_cap: 4.3e12, eps_actual: 2.01, eps_estimate: 1.94, eps_beat_pct: 3.6, beat_count: 18, total_quarters: 20,
      revenue_estimate: null, revenue_actual: null, revenue_beat_pct: null, latest_move_1d: "+3.56%", latest_outcome: "beat", latest_quarter_date: null });
    expect(facts.map((f) => [f.label, f.value])).toEqual([["Market cap", "$4.30T"], ["EPS", "$2.01"], ["EPS beats", "18/20"]]);
    expect(facts[1].sub).toBe("vs $1.94 est \u00B7 +3.6%");
    expect(noteFacts({ market_cap: null, eps_actual: null, eps_estimate: null, eps_beat_pct: null, beat_count: null, total_quarters: null,
      revenue_estimate: null, revenue_actual: null, revenue_beat_pct: null, latest_move_1d: "-2.10%", latest_outcome: null, latest_quarter_date: null })
      .map((f) => f.label)).toEqual(["Latest move"]);
    expect(noteFacts(null)).toEqual([]);
    expect(verificationLine({ supported: 12, unsupported: 1, contradicted: 0 })).toBe("13 claims checked: 12 supported, 1 unsupported, 0 contradicted");
    expect(verificationLine(null)).toBeNull();
  });

  it("the disclosures carry the ledger start date from the server and Discover names the S&P 500", () => {
    const disc = read("app/disclosures/page.tsx");
    expect(disc).toContain("export default async function DisclosuresPage()");
    expect(disc).toContain("/v1/theses/ivy-rule");
    expect(disc).toContain("The ledger began {fmtLongDate(start)}");
    expect(disc).not.toMatch(/LedgerStartDate|its start date/);
    expect(disc).toContain("The ledger&apos;s start date is shown on Ivy&apos;s page.");
    const discover = read("app/discover/page.tsx");
    expect(discover).toContain("across the S&amp;P 500 right now");
    expect(discover).not.toContain("your universe");
  });

  it("no absolute the disclosures do not back", () => {
    const home = read("app/page.tsx");
    for (const banned of ["No confident hallucinations", "the numbers are exact", "checked before you see it"]) {
      expect(home, banned).not.toContain(banned);
    }
    expect(home).toContain("unsupported ones shown as unsupported");
    expect(home).toContain("marks each one supported, unsupported or contradicted");
    expect(home).toContain("the check reduces errors, it does not remove them");
    const disc = read("app/disclosures/page.tsx");
    expect(disc).toContain("each claim is marked supported, unsupported or contradicted");
    expect(disc).toContain("the marks are shown with the note");
    // the marks really are shown with the note
    const ticker = read("app/tickers/[symbol]/page.tsx");
    expect(ticker).toMatch(/unsupported\} unsupported/);
    expect(ticker).toMatch(/contradicted\} contradicted/);
  });

  it("the real-page block is the ticker page's own headline component on the stored MU stat, fetched on the server", async () => {
    const home = read("app/page.tsx");
    expect(home).toContain("<RealStockPage />");
    expect(home).not.toMatch(/SiteCounters|CountUp|Earnings reactions measured|Analyst actions since/);
    const block = read("components/RealStockPage.tsx");
    expect(block).toContain("export default async function RealStockPage()");
    expect(block).toContain("/v1/discover/insight/${REAL_PAGE_SYMBOL}");
    expect(block).toContain('REAL_PAGE_SYMBOL = "MU"');
    expect(block).toContain("if (!hasInsight(view)) return null;");
    expect(block).toContain("<InsightHeadline insight={view.insight} rule={view.rule} asOf={view.as_of} />");
    expect(block).toContain("See {REAL_PAGE_NAME}&apos;s full page");
    expect(block).not.toMatch(/[0-9]+%|\$[0-9]/);                                   // no typed figure
    const ticker = read("app/tickers/[symbol]/page.tsx");
    expect(ticker).toContain("<InsightHeadline insight={insight} rule={insightRule} asOf={insightAsOf} />");
    expect(ticker).not.toContain("How this was computed: {insightRule}");             // one rendering, not two
    const { computedHowLine, insightAsOfLine, hasInsight } = await import("@/lib/insightHeadline");
    expect(computedHowLine("Compared this stock's beat rate to the S&P 500 median beat rate")).toBe("How this was computed: Compared this stock's beat rate to the S&P 500 median beat rate");
    expect(computedHowLine(null)).toBeNull();
    expect(insightAsOfLine("2026-09-24")).toBe("As of Sep 24, 2026");
    expect(insightAsOfLine(null)).toBeNull();
    expect(hasInsight({ insight: "x", rule: null, as_of: null })).toBe(true);
    expect(hasInsight({ insight: null, rule: null, as_of: null })).toBe(false);
    expect(hasInsight(null)).toBe(false);
  });
});
