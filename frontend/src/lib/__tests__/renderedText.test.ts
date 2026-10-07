// @vitest-environment jsdom
/** A quantity renders exactly as its text. The MU Overview and an Ask Ivy answer are rendered to DOM and each paragraph's text
 * is read back character for character against the source sentence; the spans carrying receipts add no spacing of their own
 * (no tabular figures, letter-spacing, word-spacing, gap or inline-block pieces; jsdom has no layout, so the class list is the
 * guard); names ("S&P 500", "52-week", "1-day") are never receipts. */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AskIvy } from "@/components/AskIvy";
import { Briefing } from "@/components/Briefing";
import { answerParts } from "@/lib/questions";
import type { BriefingSentence, QuestionAnswer } from "@/lib/api";

const MU: BriefingSentence[] = [
  { key: "profile", rule: "r", as_of: "2026-10-05", inputs: [{ name: "market cap", value: "$1.2 trillion", as_of: "Oct 6, 4:00 PM ET", source: "s" }],
    text: "Micron Technology, Inc. designs, manufactures, and sells memory and storage products. It's part of the S&P 500's Information Technology sector (Semiconductors), worth about $1.2 trillion." },
  { key: "happening", rule: "r", as_of: "2026-10-06", inputs: [{ name: "quote", value: "$1,045.56", as_of: "Oct 6, 4:00 PM ET", source: "s" }, { name: "quote time", value: "Oct 6, 4:00 PM ET", as_of: "Oct 6, 4:00 PM ET", source: "s" },
    { name: "52-week high", value: "$1,213.37", as_of: "2026-06-25", source: "s" }],
    text: "MU is at $1,045.56 (Oct 6, 4:00 PM ET), 13.8% below its 52-week high of $1,213.37 (Jun 25, 2026), up 11.4% over three months. Reported Sep 30, 2026 after the close: EPS $33.42 against a $32.56 estimate, a beat; the stock moved +3.0% the next session." },
];
const ASK: QuestionAnswer = { key: "ask", question: "How did it react?", idea: "", rule: "r", as_of: "2026-10-01", as_of_kind: "observed",
  inputs: [{ name: "1-day move", value: "+3.0%", as_of: "2026-10-01", source: "s" }, { name: "session the move was measured over", value: "Oct 1, 2026", as_of: "2026-10-01", source: "s" },
    { name: "typical move", value: "±7.0%", as_of: "2026-06-24", source: "s" }],
  data: "The stock rose +3.0% over the next session, Oct 1, 2026, which was less than usual given that it moves ±7.0% on a typical report; realized volatility over 20-day windows is quiet." };
const SPACING = /tabular-nums|tracking-|letter-spacing|word-spacing|\bgap-|inline-block|inline-flex|space-x-/;

function paragraphs(html: string, selector: string): HTMLElement[] {
  document.body.innerHTML = html;
  return Array.from(document.querySelectorAll<HTMLElement>(selector));
}

describe("rendered quantities", () => {
  it("the MU Overview's paragraphs read back exactly as their sentences, with no spacing class on any span", () => {
    const html = renderToStaticMarkup(createElement(Briefing, { sentences: MU }));
    const paras = paragraphs(html, "p.text-lg");
    expect(paras.length).toBe(2);
    paras.forEach((p, i) => {
      expect(p.textContent).toBe(MU[i].text);
      p.querySelectorAll("span").forEach((span) => expect(span.className).not.toMatch(SPACING));
    });
    const receipts = paras[1].querySelectorAll("span[title]");
    expect(Array.from(receipts).map((s) => s.textContent)).toEqual(["$1,045.56", "Oct 6, 4:00 PM ET", "13.8%", "$1,213.37", "Jun 25, 2026", "11.4%", "Sep 30, 2026", "$33.42", "$32.56", "+3.0%"]);
    expect(Array.from(paras[0].querySelectorAll("span[title]")).map((s) => s.textContent)).toEqual(["$1.2 trillion"]);   // "S&P 500" is a name
  });
  it("an Ask Ivy answer reads back exactly, and window names are never receipts", () => {
    const html = renderToStaticMarkup(createElement(AskIvy, { symbol: "MU", name: "Micron Technology", initialAnswer: ASK }));
    const paras = paragraphs(html, "p.text-foreground\\/90");
    expect(paras.length).toBe(1);
    expect(paras[0].textContent).toBe(ASK.data);
    paras[0].querySelectorAll("span").forEach((span) => expect(span.className).not.toMatch(SPACING));
    expect(Array.from(paras[0].querySelectorAll("span[title]")).map((s) => s.textContent)).toEqual(["+3.0%", "Oct 1, 2026", "±7.0%"]);
    const parts = answerParts("It's part of the S&P 500, 13.8% below its 52-week high over 20-day and 1-day windows, 1,254 sessions.", []);
    expect(parts.map((p) => p.text).join("")).toContain("S&P 500");
    expect(parts.filter((p) => p.receipt !== undefined).map((p) => p.text)).toEqual(["13.8%", "1,254"]);
  });
});
