import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import GLOSSARY from "@/lib/glossary";
import { TERMS } from "@/lib/glossaryTerms";

// The word "stored" never appears in visible copy (Sam, 2026-10-19): a visitor reads "on file", or nothing. This scans every JSX text
// and every string or template literal in app/, components/ and lib/ (comments are not literals, so they never count), and every
// glossary entry. A one-word value ("stored", a cache source's name in lib/siteStats) is data, not copy. backend
// tests/test_no_stored_word.py holds the same rule for the API's text.
const STORED = /\bstored\b/i;

const SRC = join(__dirname, "..", "..");
const walk = (dir: string): string[] => readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)]));
const FILES = ["app", "components", "lib"].flatMap((d) => walk(join(SRC, d)))
  .filter((f) => /\.tsx?$/.test(f) && !f.includes("__tests__") && !f.includes(join("app", "admin")) && !f.endsWith(".d.ts"));

function texts(file: string): string[] {
  const sf = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: string[] = [];
  const visit = (n: ts.Node) => {
    if (ts.isImportDeclaration(n) || ts.isExportDeclaration(n)) return;
    if (ts.isJsxText(n)) out.push(n.getText(sf).replace(/\s+/g, " ").trim());
    else if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) { if (n.text.trim().toLowerCase() !== "stored") out.push(n.text); }
    else if (ts.isTemplateExpression(n)) out.push([n.head.text, ...n.templateSpans.map((sp) => sp.literal.text)].join(" … "));
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

describe("visible copy never says stored", () => {
  it("catches the word and passes on file", () => {
    expect(STORED.test("No EPS figure is stored for this report.")).toBe(true);
    expect(STORED.test("No EPS figure is on file for this report.")).toBe(false);
    expect(STORED.test("restored")).toBe(false);
  });

  it("the glossary never says stored", () => {
    const found = [...TERMS.flatMap((t) => [t.term, t.explanation, ...(t.match ?? [])]), ...Object.values(GLOSSARY).map(String)].filter((t) => STORED.test(t));
    expect(found).toEqual([]);
  });

  it("no page copy says stored", () => {
    expect(FILES.length).toBeGreaterThan(50);
    const found = FILES.flatMap((f) => texts(f).filter((t) => STORED.test(t)).map((t) => `${f.slice(SRC.length + 1)}: ${JSON.stringify(t.slice(0, 120))}`));
    expect(found).toEqual([]);
  });
});
