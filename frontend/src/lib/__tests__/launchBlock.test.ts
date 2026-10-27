import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { shortCompanyName } from "@/lib/companyName";
import { analyticsAllowed, readConsent, writeConsent } from "@/lib/consent";
import { tickerTitle } from "@/lib/pageTitles";
import { PUBLIC_PATHS, sitemapEntries } from "@/app/sitemap";

const SRC = join(__dirname, "..", "..");

describe("the launch block (2026-10-12)", () => {
  it("titles each ticker page in Sam's form", () => {
    expect(tickerTitle("TSLA", "Tesla, Inc.")).toBe("Tesla (TSLA) earnings, options and research | Alert Interface");
    expect(tickerTitle("JPM", "JPMorgan Chase & Co.")).toBe("JPMorgan Chase (JPM) earnings, options and research | Alert Interface");
    expect(tickerTitle("NVR", null)).toBe("NVR earnings, options and research | Alert Interface");
  });

  it("shortens company names as the backend does", () => {
    expect(shortCompanyName("The Home Depot, Inc.")).toBe("Home Depot");
    expect(shortCompanyName("The Cigna Group")).toBe("Cigna");
    expect(shortCompanyName("Johnson & Johnson")).toBe("Johnson & Johnson");
    expect(shortCompanyName(null)).toBeNull();
    expect(shortCompanyName("Goldman Sachs Group, Inc. (The)")).toBe("Goldman Sachs");
    expect(shortCompanyName("PepsiCo, Inc. Common Stock")).toBe("PepsiCo");
    expect(shortCompanyName("Workday, Inc. Class A Common Stock")).toBe("Workday");
  });

  it("records nothing before the visitor accepts analytics", () => {
    const store = new Map<string, string>();
    const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } };
    expect(readConsent(storage)).toBeNull();
    expect(analyticsAllowed(readConsent(storage))).toBe(false);
    writeConsent("declined", storage);
    expect(analyticsAllowed(readConsent(storage))).toBe(false);
    writeConsent("accepted", storage);
    expect(analyticsAllowed(readConsent(storage))).toBe(true);
    const provider = readFileSync(join(SRC, "components", "PostHogProvider.tsx"), "utf8");
    expect(provider).toMatch(/!analyticsAllowed\(consent\)\) return;/);
    expect(provider.indexOf("analyticsAllowed(consent)")).toBeLessThan(provider.indexOf("posthog.init("));
  });

  it("lists every public page and every active ticker in the sitemap, and robots points at it", () => {
    const entries = sitemapEntries(["AAPL", "TSLA"], new Date("2026-10-12T00:00:00Z"));
    expect(entries.map((e) => e.url)).toEqual([...PUBLIC_PATHS.map((p) => `https://alertinterface.com${p === "/" ? "" : p}`), "https://alertinterface.com/tickers/AAPL", "https://alertinterface.com/tickers/TSLA"]);
    expect(entries.every((e) => e.lastModified)).toBe(true);
    const robots = readFileSync(join(SRC, "app", "robots.ts"), "utf8");
    expect(robots).toContain("sitemap.xml");
    const layout = readFileSync(join(SRC, "app", "layout.tsx"), "utf8");
    expect(layout).toContain("metadataBase: new URL(\"https://alertinterface.com\")");
    expect(layout).toMatch(/alternates: \{ canonical: "\.\/" \}/);
  });

  it("a ticker with no research note is empty, not an error, and an empty actions table has no toggle", () => {
    const page = readFileSync(join(SRC, "app", "tickers", "[symbol]", "page.tsx"), "utf8");
    expect(page).toContain('if (!n) { setNoteStatus("empty"); return; }');
    expect(page).toContain("detail.total_all > 0 && (");
    const api = readFileSync(join(SRC, "lib", "api.ts"), "utf8");
    expect(api).toMatch(/research-notes\?symbol=\$\{encodeURIComponent\(symbol\)\}`\)\.then\(\(n\) => n \?\? null\)/);
  });
});
