import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { axisDay, fmtDate, fmtDateTime } from "@/lib/dates";

// DESIGN.md, enforced: one date format (lib/dates and nowhere else), one underline style (.explain-term), one type scale for headings.
const SRC = join(__dirname, "../..");
function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) return f === "__tests__" ? [] : files(p);
    return /\.(tsx?|ts)$/.test(p) ? [p] : [];
  });
}
const SOURCES = ["app", "components", "lib"].flatMap((d) => files(join(SRC, d))).map((p) => ({ p: p.slice(SRC.length + 1), src: readFileSync(p, "utf8") }));
const code = (src: string) => src.split("\n").map((l, i) => ({ l, i: i + 1 })).filter(({ l }) => !/^\s*(\/\/|\*|\/\*)/.test(l));

describe("one date format", () => {
  it("formats a date and a time one way each", () => {
    expect(fmtDate("2026-10-15")).toBe("Oct 15, 2026");
    expect(fmtDate("2026-01-01")).toBe("Jan 1, 2026");                         // a calendar day never moves with the zone
    expect(fmtDateTime(1792094400)).toBe("Oct 15, 2026, 4:00 PM ET");
    expect(fmtDateTime("2026-10-15T20:00:00+00:00")).toBe("Oct 15, 2026, 4:00 PM ET");
    expect(fmtDate(null)).toBeNull();
    expect(axisDay("2026-10-15")).toBe("Oct 15");                              // chart axes alone may shorten
  });
  it("no page, component or library formats a date outside lib/dates", () => {
    const hits = SOURCES.filter(({ p }) => p !== "lib/dates.ts").flatMap(({ p, src }) => code(src)
      .filter(({ l }) => /toLocaleDateString\(|toLocaleTimeString\(|toLocaleString\("en-US", \{[^}]*(month|hour|day|year)/.test(l))
      .map(({ l, i }) => `${p}:${i}: ${l.trim().slice(0, 100)}`));
    expect(hits).toEqual([]);
  });
  it("no page prints a raw ISO date: a date field or a sliced timestamp goes through lib/dates", () => {
    const RAW = /\$\{[\w?.]+\.slice\(0, 10\)\}|(?<![=(])\{[\w?.]+\.slice\(0, 10\)\}|\$\{[\w?.]*(?:chain_date|expiration_used|snapshot_date|options_as_of|filing_date|option_expiration)\}|(?<![=(])\{[\w?.]*(?:chain_date|expiration_used|snapshot_date|options_as_of|filing_date|option_expiration)\}/;
    const hits = SOURCES.filter(({ p }) => p.endsWith(".tsx") || p.startsWith("lib/")).flatMap(({ p, src }) => code(src)
      .filter(({ l }) => RAW.test(l)).map(({ l, i }) => `${p}:${i}: ${l.trim().slice(0, 100)}`));
    expect(hits).toEqual([]);
  });
});

describe("one underline style", () => {
  it("no page or component carries an underline class; explanations use .explain-term", () => {
    const hits = SOURCES.filter(({ p }) => p.endsWith(".tsx")).flatMap(({ p, src }) => code(src)
      .filter(({ l }) => /className=[^>]*(?<![-\w])(?:hover:)?underline(?:-offset-\d|\b)(?!-)/.test(l) || /decoration-dotted|decoration-(?:solid|dashed)/.test(l))
      .map(({ l, i }) => `${p}:${i}: ${l.trim().slice(0, 100)}`));
    expect(hits).toEqual([]);
    expect(readFileSync(join(SRC, "app/globals.css"), "utf8")).toMatch(/\.explain-term \{[^}]*text-decoration-style: dotted/);
    expect(readFileSync(join(SRC, "components/ticker/ExplainTip.tsx"), "utf8")).toContain("explain-term");
  });
});

describe("one type scale", () => {
  it("every h1 is display and every heading h2 is headline or display", () => {
    const h1 = SOURCES.flatMap(({ p, src }) => [...src.matchAll(/<h1 className="([^"]*)"/g)].filter((m) => !/\btext-display\b|\bopen-h1\b/.test(m[1])).map((m) => `${p}: h1 ${m[1]}`));
    const h2 = SOURCES.flatMap(({ p, src }) => [...src.matchAll(/<h2 className="([^"]*)"/g)]
      .filter((m) => !/uppercase/.test(m[1]) && !/\btext-(?:headline|display)\b/.test(m[1])).map((m) => `${p}: h2 ${m[1]}`));
    expect([...h1, ...h2]).toEqual([]);
    expect(readFileSync(join(SRC, "../tailwind.config.ts"), "utf8")).toMatch(/display: \[[^\]]*\][\s\S]*headline: \[[\s\S]*body: \[[\s\S]*small: \[/);
  });
});
