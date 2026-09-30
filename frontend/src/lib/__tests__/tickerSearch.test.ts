import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { Ticker } from "@/lib/api";
import { SEARCH_LIMIT, matchTickers, tickerPath } from "@/lib/tickerSearch";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

const t = (symbol: string, name: string, cap: number): Ticker => ({
  id: symbol, symbol, name, sector: null, industry: null, exchange: null, market_cap: cap, is_active: true, index_member: true, next_earnings_date: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
});
const LIST = [t("MSFT", "Microsoft Corporation", 3e12), t("MU", "Micron Technology, Inc.", 1e11), t("AMD", "Advanced Micro Devices", 2e11),
              t("AAPL", "Apple Inc.", 3.5e12), t("A", "Agilent Technologies", 4e10), t("AMAT", "Applied Materials", 1.5e11)];

describe("one ticker matcher for every search box", () => {
  it("matches symbol or company name: exact symbol first, then symbol prefix, then market cap", () => {
    expect(matchTickers(LIST, "micro").map((x) => x.symbol)).toEqual(["MSFT", "AMD", "MU"]);   // by cap: all name matches
    expect(matchTickers(LIST, "a").map((x) => x.symbol)).toEqual(["A", "AAPL", "AMD", "AMAT", "MSFT"]);   // exact, prefixes by cap, then the rest
    expect(matchTickers(LIST, "mu").map((x) => x.symbol)).toEqual(["MU"]);
    expect(matchTickers(LIST, "  apple ").map((x) => x.symbol)).toEqual(["AAPL"]);
    expect(matchTickers(LIST, "")).toEqual([]);
    expect(matchTickers(LIST, "zzz")).toEqual([]);
    expect(matchTickers(Array.from({ length: 20 }, (_, i) => t(`X${i}`, "Xylo", i)), "x")).toHaveLength(SEARCH_LIMIT);
    expect(tickerPath(matchTickers(LIST, "micro"))).toBe("/tickers/MSFT");
    expect(tickerPath([])).toBeNull();
  });

  it("Build's picker and the search box both call it, and Build keeps no matcher of its own", () => {
    const build = read("app/build/page.tsx");
    expect(build).toContain("useMemo(() => matchTickers(tickers, query), [tickers, query])");
    expect(build).not.toMatch(/\(t\.name \?\? ""\)\.toLowerCase\(\)\.includes/);
    const box = read("components/TickerSearch.tsx");
    expect(box).toContain("matchTickers(tickers ?? [], query)");
    expect(box).toContain('router.push(path)');
    expect(box).toMatch(/if \(e\.key === "Enter"\) \{ e\.preventDefault\(\); go\(tickerPath\(matches\)\); \}/);
    expect(box).toContain("go(`/tickers/${t.symbol}`)");
  });

  it("the header carries the box on every page, collapsed to an icon at phone width; the home page has it first, labelled", () => {
    const layout = read("app/layout.tsx");
    expect(layout).toContain("<HeaderTickerSearch />");
    expect(layout.indexOf("<NavLinks />")).toBeLessThan(layout.indexOf("<HeaderTickerSearch />"));
    const box = read("components/TickerSearch.tsx");
    expect(box).toContain('className="hidden sm:block ml-auto w-56"');
    expect(box).toMatch(/className="sm:hidden ml-auto[^"]*"\s+data-testid="header-search-toggle"/);
    expect(box).toContain('<div className="sm:hidden basis-full pb-1">');
    expect(box).toContain('export const HOME_SEARCH_LABEL = "Look up a stock";');
    const home = read("app/page.tsx");
    expect(home.indexOf("<HomeTickerSearch />")).toBeLessThan(home.indexOf('<h1 className="hero-h1'));
    expect(box).toMatch(/export function HomeTickerSearch\(\) \{[\s\S]{0,300}<SearchBox autoFocus="desktop" label=\{HOME_SEARCH_LABEL\}/);
  });

  it("the home box takes focus on load from the header's breakpoint up, and never at phone width", () => {
    const box = read("components/TickerSearch.tsx");
    expect(box).toContain('export const DESKTOP_QUERY = "(min-width: 640px)";');   // Tailwind sm, where the header collapses
    expect(box).toMatch(/if \(autoFocus === "desktop" && !window\.matchMedia\(DESKTOP_QUERY\)\.matches\) return;\s*inputRef\.current\?\.focus\(\);/);
    expect(box).not.toMatch(/autoFocus=\{autoFocus\}/);      // focus is decided in the effect, never by the attribute
    expect(readFileSync(join(SRC, "../tailwind.config.ts"), "utf8")).not.toMatch(/screens:\s*\{[^}]*sm:/);   // sm is Tailwind's default 640px
    expect(box).toContain("hidden sm:block");   // the header collapses at the same breakpoint
  });
});
