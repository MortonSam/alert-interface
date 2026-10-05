import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { briefingParagraph, hasBriefing, sentenceReceipt, sourceLine } from "@/lib/briefing";
import type { BriefingSentence } from "@/lib/api";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

const S: BriefingSentence[] = [
  { key: "catalyst", text: "Next earnings Oct 14, 2026, after the close, 9 days away, confirmed by the company (press release).", rule: "Next report from the stored earnings calendar.",
    as_of: "2026-10-14", inputs: [{ name: "next earnings date", value: "Oct 14, 2026", as_of: "2026-10-14", source: "finnhub" }, { name: "days away", value: "9", as_of: "2026-10-05", source: null }] },
  { key: "pattern", text: "Beat estimates in 15 of 20 stored quarters and fell the next session after 8 of those 15 beats (53%), so a beat alone has not been a buy signal.",
    rule: "Earnings quarters with a stored 1-day move; a share of 50% or more reads as no buy signal.", as_of: "2026-06-25",
    inputs: [{ name: "stored quarters", value: "20", as_of: "2026-06-25", source: "historical_reactions" }] },
];

describe("the briefing renders the API's sentences and receipts, nothing typed", () => {
  it("joins the sentences in API order and reads each receipt from the sentence", () => {
    expect(briefingParagraph(S)).toBe(S[0].text + " " + S[1].text);
    expect(sentenceReceipt(S[0])).toEqual({ how: "How this was computed: Next report from the stored earnings calendar.", asOf: "As of Oct 14, 2026" });
    expect(sentenceReceipt({ ...S[1], rule: "", as_of: null })).toEqual({ how: null, asOf: null });
    expect(sourceLine(S[0].inputs[0])).toBe("next earnings date: Oct 14, 2026 (As of Oct 14, 2026; finnhub)");
    expect(sourceLine({ name: "quote time", value: "Oct 5, 4:00 PM ET", as_of: "Oct 5, 4:00 PM ET", source: "last trade" })).toBe("quote time: Oct 5, 4:00 PM ET (Oct 5, 4:00 PM ET; last trade)");
    expect(sourceLine({ name: "days away", value: "9", as_of: null, source: null })).toBe("days away: 9");
    expect(hasBriefing({ symbol: "MU", name: null, sentences: S })).toBe(true);
    expect(hasBriefing({ symbol: "MU", name: null, sentences: [] })).toBe(false);
    expect(hasBriefing(null)).toBe(false);
  });

  it("the component carries no number, date or threshold of its own and renders nothing without sentences", () => {
    const src = read("components/Briefing.tsx").replace(/className="[^"]*"/g, "");
    expect(src).not.toMatch(/[0-9]{2,}|[0-9]%|\$[0-9]/);
    expect(src).not.toMatch(/new Date\(|Date\.now\(/);
    expect(src).toContain("if (!sentences.length) return null;");
    expect(src).toContain("sentenceReceipt(s)");
    expect(src).toContain("<summary");
    expect(src).toContain("sourceLine(inp)");
  });
});
