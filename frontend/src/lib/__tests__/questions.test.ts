import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { answerParts, hasQuestions, questionsHeader, receiptFor } from "@/lib/questions";
import GLOSSARY from "@/lib/glossary";
import { GLOSSARY_LINKS } from "@/lib/briefing";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");
const INPUTS = [
  { name: "1-day move", value: "+3.0%", as_of: "2026-09-30", source: "stored bars through the seeder's window" },
  { name: "typical move", value: "±7.0%", as_of: "2026-06-25", source: "mean absolute 1-day move" },
  { name: "reports moving more", value: "15", as_of: "2026-06-25", source: null },
  { name: "reports in the sample", value: "20", as_of: "2026-06-25", source: null },
];
const DATA = "MU moved +3.0% the next session after its Sep 30, 2026 report, against a typical ±7.0% over the last 20 reports; 15 of those reports moved it more.";

describe("the question strip renders answers from the API with a receipt on every number", () => {
  it("every number in a data sentence gets the input behind it; glossary terms link once per answer", () => {
    const parts = answerParts(DATA, INPUTS);
    const numbers = parts.filter((p) => p.receipt !== undefined);
    expect(numbers.map((p) => p.text)).toEqual(["+3.0%", "30", "2026", "±7.0%", "20", "15"]);
    expect(receiptFor("+3.0%", INPUTS)).toBe("1-day move: +3.0% (As of Sep 30, 2026; stored bars through the seeder's window)");
    expect(receiptFor("20", INPUTS)).toBe("reports in the sample: 20 (As of Jun 25, 2026)");
    expect(parts.map((p) => p.text).join("")).toBe(DATA);                                 // nothing lost or reordered
    const twice = answerParts("A beat after a beat; the 1-day move and the 1-day move.", []);
    expect(twice.filter((p) => p.term).map((p) => p.term)).toEqual(["beat", "1-day move"]);   // one link per term
    expect(questionsHeader("Micron Technology")).toBe("Questions about Micron Technology, answered by Ivy from this page's data");
    expect(hasQuestions({ questions: [] })).toBe(false);
    expect(hasQuestions(null)).toBe(false);
    for (const [, term] of GLOSSARY_LINKS) expect(GLOSSARY[term], term).toBeTruthy();
  });

  it("the component carries no number of its own, opens one question at a time, and logs the open", () => {
    const src = read("components/QuestionStrip.tsx");
    expect(src.replace(/className="[^"]*"/g, "")).not.toMatch(/[0-9]{2,}|[0-9]%|\$[0-9]/);
    expect(src).toContain("if (!hasQuestions(data)) return null;");
    expect(src).toContain("const next = open === key ? null : key;");                         // one open at a time
    expect(src).toContain('posthog.capture("question_opened", { ticker: symbol, question: key })');
    expect(src).toContain("title={part.receipt ?? undefined}");                               // the receipt on the number
    const page = read("app/tickers/[symbol]/page.tsx");
    expect(page).toContain('<div data-slot="question-strip"><QuestionStrip symbol={upperSymbol} /></div>');
  });
});
