import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { answerParts, asOfLabel, hasQuestions, questionsHeader, receiptFor } from "@/lib/questions";
import { sentenceReceipt } from "@/lib/briefing";
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
    expect(numbers.map((p) => p.text)).toEqual(["+3.0%", "Sep 30, 2026", "±7.0%", "20", "15"]);          // a date is one span
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

  it("every quantity in every rendered answer is one whole span: no receipt span starts or ends on punctuation, no number is split", () => {
    const answers = [
      "MU moved +3.0% the next session after its Sep 30, 2026 report, against a typical ±7.0% over the last 20 reports; 15 of those reports moved it more.",
      "MU fell the next session after 11 of its last 18 beats (61%).",
      "MU goes ex-dividend on Oct 14, 2026 with a $0.15 per-share dividend.",
      "Over the last 20 reports MU has moved ±7.0% on average the session after reporting; its largest were +15.7% (Jun 24, 2026) and -16.2% (Dec 18, 2024).",
      "On Sep 29, 2026 FICO moved -26.5%, about 17 times a typical day for it and larger than 99.8% of its daily moves over the past 5 years (1,255 sessions).",
      "FICO's realized volatility over the last 20 sessions is 123.7% annualized, more active than 89% of its own 20-day windows over the past year.",
      "Options price a move of about ±6.0% for the Oct 6, 2026 report; over the last 20 reports STZ has moved ±4.0% on average, so the market is pricing more than usual.",
      "On its 17 past upgrade days MU's median move was +1.8%, and in 71% of them the five-session move kept the first day's direction.",
      "MU is at $1,063.96 (Oct 5, 4:00 PM ET), 12.3% below its 52-week high of $1,213.37 (Jun 25, 2026), up 8.0% over three months.",
      "Micron Technology designs memory. It's part of the S&P 500's Information Technology sector (Semiconductors), worth about $1.2 trillion.",
    ];
    for (const text of answers) {
      const parts = answerParts(text, []);
      expect(parts.map((p) => p.text).join("")).toBe(text);
      const spans = parts.filter((p) => p.receipt !== undefined).map((p) => p.text);
      for (const span of spans) {
        expect(span, `${span} in: ${text}`).not.toMatch(/^[\s.,;:()]|[\s.,;:(]$/);                  // never starts or ends on punctuation
        expect(span, `${span} split`).not.toMatch(/^\d+$/.test(span) && text.includes(span + ".") && /\d/.test(text[text.indexOf(span + ".") + span.length + 1] ?? "") ? /./ : /$^/);
      }
      // the whole quantities survive as single spans
      for (const whole of text.match(/\$[\d,]+\.\d+(?: (?:million|billion|trillion))?|[+\-±]?\d+(?:\.\d+)?%|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{4}/g) ?? []) {
        expect(spans, `${whole} should be one span in: ${text}`).toContain(whole);
      }
    }
    expect(answerParts("a 1-day move and a 20-day window", []).filter((p) => p.receipt !== undefined)).toEqual([]);   // windows are words
  });

  it("an as-of is when we knew: kinds are worded, and a date after today is never shown", () => {
    const today = new Date("2026-10-06T12:00:00Z");
    expect(asOfLabel("2026-10-06", "estimated", today)).toBe("Estimated, as of Oct 6, 2026");
    expect(asOfLabel("2026-09-30", "declared", today)).toBe("Declared Sep 30, 2026");
    expect(asOfLabel("2026-10-05", "observed", today)).toBe("As of Oct 5, 2026");
    expect(asOfLabel("2026-10-14", "observed", today)).toBeNull();                                 // the ex-date is not an as-of
    expect(asOfLabel(null, "observed", today)).toBeNull();
    expect(sentenceReceipt({ key: "happening", text: "x", rule: "r", as_of: "2026-10-28", inputs: [] }, today).asOf).toBeNull();
    expect(sentenceReceipt({ key: "happening", text: "x", rule: "r", as_of: "2026-10-05", inputs: [] }, today).asOf).toBe("As of Oct 5, 2026");
  });

  it("the component carries no number of its own, opens one question at a time, and logs the open", () => {
    const src = read("components/QuestionStrip.tsx");
    expect(src.replace(/className="[^"]*"/g, "")).not.toMatch(/[0-9]{2,}|[0-9]%|\$[0-9]/);
    expect(src).toContain("if (!hasQuestions(data)) return null;");
    expect(src).toContain("const next = open === key ? null : key;");                         // one open at a time
    expect(src).toContain('posthog.capture("question_opened", { ticker: symbol, question: key })');
    expect(src).toContain("title={part.receipt ?? undefined}");                               // the receipt on the number
    expect(src).toContain("asOfLabel(q.as_of, q.as_of_kind)");
    const page = read("app/tickers/[symbol]/page.tsx");
    expect(page).toContain('<div data-slot="question-strip"><QuestionStrip symbol={upperSymbol} /></div>');
  });

  it("the ask box renders only behind the flag, types no number, and shows every number through the tokenizer with its receipt", () => {
    const strip = read("components/QuestionStrip.tsx");
    expect(strip).toContain("{data!.ask_enabled && <AskIvy symbol={symbol} name={data!.name ?? symbol} />}");   // the flag gates it
    const src = read("components/AskIvy.tsx");
    const copy = src.replace(/className="[^"]*"/g, "").replace(/maxLength=\{300\}/, "");
    expect(copy).not.toMatch(/[0-9]{2,}|[0-9]%|\$[0-9]/);                                                        // no typed figure
    expect(src).toContain("answerParts(answer.data, answer.inputs)");                                              // the strip's tokenizer
    expect(src).toContain("title={part.receipt ?? undefined}");                                                    // the receipt on the number
    expect(src).toContain("asOfLabel(answer.as_of, answer.as_of_kind)");                                           // dated by its facts
    expect(src).not.toMatch(/recommend(?!ations\.)/i);                                                            // the only mention says there are none
    expect(src).toContain('posthog.capture("question_asked"');
  });
});
