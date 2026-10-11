import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import GLOSSARY from "@/lib/glossary";
import { TERMS } from "@/lib/glossaryTerms";
import { explainSegments } from "@/lib/explainSegments";

const SRC = join(__dirname, "../..");
const walk = (dir: string): string[] => readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)]));
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const exactCase = (v: string) => v === v.toUpperCase() || /[&/]/.test(v);
const found = (v: string, text: string) => new RegExp(`(?<![A-Za-z0-9])${esc(v)}(?![A-Za-z0-9])`, exactCase(v) ? "" : "i").test(text);

describe("the glossary", () => {
  it("explains every term in one or two plain sentences with no other listed term inside", () => {
    expect(TERMS.length).toBeGreaterThanOrEqual(60);
    for (const t of TERMS) {
      const sentences = t.explanation.split(/(?<=[.!?])\s+(?=[A-Z])/);
      expect(sentences.length, t.key).toBeLessThanOrEqual(2);
      expect(t.explanation.split(/\s+/).length, t.key).toBeLessThanOrEqual(45);
      for (const o of TERMS) {
        if (o === t) continue;
        for (const v of o.match) expect(found(v, t.explanation), `${t.key} uses "${v}" (${o.key})`).toBe(false);
      }
      expect(GLOSSARY[t.key], t.key).toBe(t.explanation);
    }
  });
  it("attaches the explanation to every term in a sentence, longest match first, exact case for acronyms", () => {
    const segs = explainSegments("RV rank 85 of 100, IV rich; one session dominates the 20-day window.");
    expect(segs.filter((s) => s.key).map((s) => [s.text, s.key])).toEqual([["RV rank", "rv-rank"], ["IV rich", "vol-regime"], ["one session dominates the 20-day window", "one-session-dominates"]]);
    expect(explainSegments("the iv of prose").every((s) => !s.key)).toBe(true);
    expect(explainSegments("no terms here").map((s) => s.text).join("")).toBe("no terms here");
  });
});

// Customer-facing text: every page and component except the home page. A term in literal JSX text must sit inside an ExplainTip
// (or reach the page through <Explained text=...>); new jargon can never ship unexplained.
const PAGES = walk(join(SRC, "app")).concat(walk(join(SRC, "components")))
  .filter((f) => f.endsWith(".tsx") && !f.includes("__tests__") && !f.endsWith(join("app", "page.tsx")) && !f.endsWith("Explained.tsx") && !f.includes(join("app", "admin")));

function unexplained(src: string): string[] {
  const stripped = src
    .replace(/<ExplainTip\b[\s\S]*?<\/ExplainTip>/g, " ")               // explained terms
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, " ")                             // JSX comments
    .replace(/<Explained\b[^>]*\/>/g, " ");
  const decode = (t: string) => t.replace(/&apos;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">");
  const texts = [...stripped.matchAll(/[>}]([^<>{}]*[A-Za-z][^<>{}]*)[<{]/g)].map((m) => decode(m[1]))   // literal JSX text between tags
    .filter((t) => !/;\s*(\n|$)| = |==|!=|=>|\bconst\b|\breturn\b|\?\.|&&|\|\||\buse[A-Z]|`|^\s*\/\//.test(t));   // not code between a > and a <
  const hits: string[] = [];
  for (const text of texts) for (const t of TERMS) for (const v of t.match) if (found(v, text)) hits.push(`"${v}" in "${text.trim().slice(0, 60)}"`);
  return hits;
}

describe("no term renders without its explanation", () => {
  for (const f of PAGES) {
    it(f.replace(SRC, "src"), () => {
      expect(unexplained(readFileSync(f, "utf8"))).toEqual([]);
    });
  }
});
