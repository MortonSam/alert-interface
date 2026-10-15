import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";
// @ts-expect-error: a plain module shared with the browser check (scripts/public-pages-check.mjs)
import { FORBIDDEN, violations } from "../../../scripts/publicText.mjs";

// A public page never shows token counts, model names, costs or developer messages (2026-10-15). The browser check renders every
// public route as an anonymous visitor against a running site; this guard holds the same list over the source the gate builds:
// no page or component renders a field that carries a model name or a token count, and no copy a page writes says any of it.
const SRC = join(__dirname, "../..");
const DIRS = ["app", "components"];
// fields that hold a model name, a token count or a cost; a page may test them (=== "none", &&) but never print them
const DEV_FIELDS = /\b(?:input_tokens|output_tokens|verification_model|cost_usd|estimated_cost)\b/;
const MODEL_FIELD = /\bmodel_used\b(?!\s*(?:===|!==|&&|\)\s*&&))/;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) return f === "__tests__" ? [] : files(p);
    return p.endsWith(".tsx") ? [p] : [];
  });
}

/** The copy a file renders: JSX text and the string literals inside JSX expressions and attributes. */
function renderedCopy(src: string, name: string): string[] {
  const sf = ts.createSourceFile(name, src, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const out: string[] = [];
  const inJsx = (n: ts.Node): boolean => { for (let p = n.parent; p; p = p.parent) if (ts.isJsxExpression(p) || ts.isJsxAttribute(p)) return true; return false; };
  const visit = (n: ts.Node) => {
    if (ts.isJsxText(n) && n.text.trim()) out.push(n.text.trim());
    else if ((ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) && inJsx(n) && /\s/.test(n.text)) out.push(n.text);
    else if (ts.isTemplateExpression(n) && inJsx(n)) out.push([n.head.text, ...n.templateSpans.map((s) => s.literal.text)].join(" "));
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

const SOURCES = DIRS.flatMap((d) => files(join(SRC, d))).map((p) => ({ p: p.slice(SRC.length + 1), src: readFileSync(p, "utf8") }));

describe("public pages show no model names, token counts, costs or developer messages", () => {
  it("no page or component prints a model, token or cost field", () => {
    const hits = SOURCES.flatMap(({ p, src }) => src.split("\n").map((line, i) => ({ p, i: i + 1, line }))
      .filter(({ line }) => !line.trim().startsWith("//") && !line.trim().startsWith("*") && (DEV_FIELDS.test(line) || MODEL_FIELD.test(line))))
      .map(({ p, i, line }) => `${p}:${i}: ${line.trim().slice(0, 120)}`);
    expect(hits).toEqual([]);
  });

  it("no rendered copy names a model, a token count, a cost or a developer message", () => {
    const hits = SOURCES.flatMap(({ p, src }) => renderedCopy(src, p).flatMap((t) => violations(t).map((v: string) => `${p}: ${v}`)));
    expect(hits).toEqual([]);
  });

  it("the patterns catch what the 2026-10-12 walkthrough saw, and pass ordinary copy", () => {
    for (const bad of ["Generated 3d ago · 10-Q 2026-07-23 · 5227 tokens", "verified 3d ago · claude-opus-4-6", "claude-sonnet-4-6 · cached 5h ago",
      "Ivy's Read was written when realized volatility was unavailable and is being regenerated now that it is", "quote cache, dated by its last trade"])
      expect(violations(bad).length, bad).toBeGreaterThan(0);
    for (const ok of ["Written 5h ago · chain as of 2026-10-14", "verified 3d ago", "Max loss $240", "latest quote, dated by its last trade", "drafted by Ivy"])
      expect(violations(ok), ok).toEqual([]);
    expect(FORBIDDEN.length).toBe(4);
  });
});
