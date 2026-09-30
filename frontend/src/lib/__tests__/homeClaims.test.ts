import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

describe("home page claims the disclosures support (audit items 8, 9, 21)", () => {
  it("the sample note is labelled an illustration in its heading and status line, never a generated note", () => {
    const home = read("app/page.tsx");
    expect(home).toContain("What a note looks like: an illustration");
    expect(home).toContain("Illustration, not a generated note");
    expect(home).toContain("Illustrative figures, not a company&apos;s");
    expect(home).not.toMatch(/Generated &amp; verified|Sample note from|every number you can hover/);
    expect(home).toContain('href="/tickers/AAPL"');
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

  it("the counters render the real number first and animate only once seen", () => {
    const src = read("components/CountUp.tsx");
    expect(src).toContain('useState(value.toLocaleString("en-US"))');
    const observer = src.indexOf("new IntersectionObserver(");
    const zero = src.indexOf('setDisplay("0")');
    expect(src.split('setDisplay("0")').length - 1).toBe(1);
    expect(zero).toBeGreaterThan(observer);                       // only inside the observer's callback
    expect(zero).toBeGreaterThan(src.indexOf("triggered.current = true;"));
  });
});
