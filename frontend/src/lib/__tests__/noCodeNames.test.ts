import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import GLOSSARY from "@/lib/glossary";
import { TERMS } from "@/lib/glossaryTerms";

// Customer-facing text never names a code file, function or path. This scans the pages' own copy: JSX text, prose string literals
// (three words or more) in app/, components/ and lib/, and every glossary entry. backend tests/test_no_code_names.py holds the same
// rule for the API's text.
const CODE_PATTERNS: [string, RegExp][] = [
  ["file", /\b[\w-]+\.(?:tsx?|jsx?|py|json|md|css|sh|sql|ya?ml)\b/g],
  ["path", /\b(?:src|app|lib|components|services|routers|scripts|backend|frontend|tests|ops)\/[\w.-]/g],
  ["function", /\b[A-Za-z_][A-Za-z0-9_]*\(\)/g],
  ["identifier", /\b[a-z][a-z0-9]*_[a-z0-9_]+\b/g],
  ["identifier", /\b[a-z]+[A-Z][A-Za-z0-9]+\b/g],
];
const ALLOWED = new Set(["iPhone", "iPad", "eBay"]);
// a visitor reads what a thing is, never which vendor supplied it (2026-10-12); the one exception is the home page's licence
// credit for the price history, which names its licensor on purpose
const VENDORS = /\b(?:Finnhub|Yahoo Finance|yfinance|Intrinio|EDGAR)\b/g;
const LICENCE_CREDIT = "Five years of daily prices for every S&P 500 stock, licensed from Intrinio";

export function codeNames(text: string): string[] {
  const code = CODE_PATTERNS.flatMap(([kind, re]) => [...text.matchAll(re)].map((m) => m[0]).filter((m) => !ALLOWED.has(m)).map((m) => `${kind}: ${m}`));
  const vendors = text === LICENCE_CREDIT ? [] : [...text.matchAll(VENDORS)].map((m) => `vendor: ${m[0]}`);
  return [...code, ...vendors];
}

const SRC = join(__dirname, "..", "..");
const walk = (dir: string): string[] => readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)]));
const FILES = ["app", "components", "lib"].flatMap((d) => walk(join(SRC, d)))
  .filter((f) => /\.tsx?$/.test(f) && !f.includes("__tests__") && !f.includes(join("app", "admin")) && !f.endsWith(".d.ts")
    && !f.endsWith("displayedDates.ts"));   // a rule table only its test reads

/** Copy a visitor can read: JSX text, and string or template literals of three words or more, found by parsing the file (so code is
 *  never mistaken for text). Import paths, className values and keys are not copy. */
function prose(file: string): string[] {
  const sf = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: string[] = [];
  const visit = (n: ts.Node) => {
    if (ts.isImportDeclaration(n) || ts.isExportDeclaration(n)) return;
    if (ts.isJsxAttribute(n) && ["className", "key", "href", "src", "data-testid", "id"].includes(n.name.getText(sf))) return;
    if (ts.isJsxText(n)) {
      const t = n.getText(sf).replace(/\s+/g, " ").trim();
      if (/[A-Za-z]{2,}/.test(t)) out.push(t);
    } else if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) {
      if ((n.text.match(/ /g) ?? []).length >= 2 && !/^(https?:\/\/|\/)/.test(n.text)) out.push(n.text);
    } else if (ts.isTemplateExpression(n)) {
      const t = [n.head.text, ...n.templateSpans.map((sp) => sp.literal.text)].join(" … ");
      if ((t.match(/ /g) ?? []).length >= 2 && !t.startsWith("/")) out.push(t);     // an API path is not copy
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

describe("customer-facing text names no code", () => {
  it("catches code and passes prose", () => {
    expect(codeNames("Cutoffs come from lib/thresholds.ts.")).not.toEqual([]);
    expect(codeNames("see computeExpectedMove() and iv_rank")).toHaveLength(3);
    expect(codeNames("Put/call ratio above 1.2 reads put-heavy; U.S. markets close at 4:00 p.m. ET.")).toEqual([]);
    expect(codeNames("Reports in 3 days (estimated, Finnhub, checked today)")).toEqual(["vendor: Finnhub"]);
    expect(codeNames(LICENCE_CREDIT)).toEqual([]);
  });

  it("the glossary names no code", () => {
    const found = [...TERMS.flatMap((t) => [t.term, t.explanation]), ...Object.values(GLOSSARY).map(String)].flatMap((t) => codeNames(t).map((h) => `${h} in ${t}`));
    expect(found).toEqual([]);
  });

  it("no page copy names code", () => {
    expect(FILES.length).toBeGreaterThan(50);
    const found = FILES.flatMap((f) => prose(f).flatMap((t) => codeNames(t).map((h) => `${f.slice(SRC.length + 1)}: ${h} in ${JSON.stringify(t.slice(0, 100))}`)));
    expect(found).toEqual([]);
  });
});
