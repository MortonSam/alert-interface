import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { IVY_PAGE } from "@/lib/ivyPageCopy";
import { OLD_IVY_PATHS, PUBLIC_PATHS, publicPaths, walkthroughOn } from "@/app/sitemap";
import { ivyMode } from "@/lib/useIvyMode";
import type { IvyPage } from "@/lib/walkthrough";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

const lines = (): string[] => [
  IVY_PAGE.headline, IVY_PAGE.searchLabel, IVY_PAGE.searchPlaceholder, IVY_PAGE.quickPicks, IVY_PAGE.noWalkthrough("NVIDIA"),
  IVY_PAGE.stepFrom("NVIDIA"), IVY_PAGE.startWalk("NVIDIA"), IVY_PAGE.checkTitle, IVY_PAGE.noteFrom("NVIDIA Corporation"),
  IVY_PAGE.filingFrom("10-Q", "Aug 26, 2026"), IVY_PAGE.readFiling, IVY_PAGE.checked("398", "Nov 2, 2026"), IVY_PAGE.ideasTitle, IVY_PAGE.closing,
];

describe("the one Ivy page (Sam, 2026-11-02)", () => {
  it("says what Sam wrote, and no line has a colon, a dash, a pick or advice", () => {
    expect(IVY_PAGE.headline).toBe("Ivy reads the filings, so you understand the company.");
    expect(IVY_PAGE.closing).toBe("Ivy doesn't tell you what to buy or sell. She shows you how to decide for yourself.");
    for (const l of lines()) {
      expect(l, l).not.toMatch(/[:—–]/);
      expect(l, l).not.toMatch(/\b(?:picks?|ledger|backtest|setup|track record|win rate|you should|buy now|sell now)\b/i);
    }
  });

  it("types no count or date: they come from the API with their own dates", () => {
    const page = read("components/ivy/IvyPageView.tsx");
    expect(page).toContain("readIvyPage()");
    expect(page).toContain("C.checked(page.trust.checked.count");
    expect(page).not.toMatch(/(?<![-\w])(?:300|398|452|503)\b/);         // no count typed by hand
    expect(page).toMatch(/walkHref\(idea\.symbol, idea\.n\)/);           // each idea opens its example step
    expect(page).toContain("<StepScreen step={step} w={walk}");            // a real step, rendered by the walkthrough's own component
    expect(page).not.toMatch(/cards|ivy-trust|Ivy's Read/);                // no descriptive boxes (Sam, 2026-11-03)
  });

  it("the old Ivy stays until the walkthrough is on, and the new page shows only then (Sam, 2026-11-10)", async () => {
    expect(ivyMode(undefined)).toEqual({ mode: "loading" });
    expect(ivyMode(null)).toEqual({ mode: "old" });                         // a 404 (the flag off) or a failed read
    const served = { minutes: 3 } as IvyPage;
    expect(ivyMode(served)).toEqual({ mode: "walkthrough" });
    const route = read("app/ivy/page.tsx");
    expect(route).toContain('ivy.mode === "walkthrough" ? <IvyPageView /> : <MeetIvyPage />');
    expect(route).toContain('if (ivy.mode === "loading") return null;');
    expect(read("components/ivy/IvyFrame.tsx")).toContain('ivy.mode === "walkthrough" ? <>{children}</> : <OldIvyLayout>{children}</OldIvyLayout>');
    for (const [p, name] of [["app/ivy/desk/page.tsx", "IvyDeskPage"], ["app/ivy/trades/page.tsx", "IvyTradesPage"]]) {
      expect(read(p), p).toContain(`<OldIvyOnly><${name} /></OldIvyOnly>`);
    }
    const gate = read("components/ivy/OldIvyOnly.tsx");
    expect(gate).toContain('if (ivy.mode === "walkthrough") router.replace("/ivy");');
    expect(gate).toContain('return ivy.mode === "old" ? <>{children}</> : null;');
    expect(read("app/ivy/picks/page.tsx")).toContain('redirect("/ivy/desk")');
    expect(read("app/alerts-trades/page.tsx")).toContain('redirect("/ivy/trades")');
    // the new page is never the route's fallback: it is reached through the mode alone
    expect(read("lib/useIvyMode.ts")).toContain("fetchIvyPage()");
  });

  it("the page arrives as the right Ivy: the server's reading of the flag stands until the browser's own is in (Sam, 2026-11-11)", async () => {
    const served = { minutes: 3 } as IvyPage;
    expect(ivyMode(undefined, false)).toEqual({ mode: "old" });            // never the blank while the browser asks
    expect(ivyMode(undefined, true)).toEqual({ mode: "walkthrough" });
    expect(ivyMode(served, false)).toEqual({ mode: "walkthrough" });       // the admin token's preview, or a flag turned on since
    expect(ivyMode(null, true)).toEqual({ mode: "old" });                  // a flag turned off since, or a read that failed
    const layout = read("app/ivy/layout.tsx");
    expect(layout).not.toContain('"use client"');
    expect(layout).toContain("await walkthroughOn(process.env.NEXT_PUBLIC_API_URL, fetch, FLAG_SECONDS)");
    expect(layout).toContain("<IvyFrame walkthrough={walkthrough}>{children}</IvyFrame>");
    const frame = read("components/ivy/IvyFrame.tsx");
    expect(frame).toContain("<IvyFlag.Provider value={walkthrough}>");
    expect(frame).not.toContain("aria-busy");
    expect(read("lib/useIvyMode.ts")).toContain("return ivyMode(page, served);");
    const asked: unknown[] = [];
    const fetcher = (async (_url: string, init: unknown) => { asked.push(init); return { ok: true }; }) as unknown as typeof fetch;
    await walkthroughOn("http://api", fetcher, 60);
    await walkthroughOn("http://api", fetcher);
    expect(asked).toEqual([{ next: { revalidate: 60 } }, { next: { revalidate: 3600 } }]);
  });

  it("the sitemap lists the Desk and the Trades only while the old Ivy shows", async () => {
    expect(publicPaths(true)).toEqual(PUBLIC_PATHS);
    expect(PUBLIC_PATHS.filter((p) => p.startsWith("/ivy/"))).toEqual([]);
    expect(publicPaths(false)).toEqual(["/", "/discover", "/build", "/ivy", ...OLD_IVY_PATHS, "/disclosures"]);
    const answers = (ok: boolean) => (async () => ({ ok })) as unknown as typeof fetch;
    expect(await walkthroughOn("http://api", answers(true))).toBe(true);
    expect(await walkthroughOn("http://api", answers(false))).toBe(false);
    expect(await walkthroughOn("http://api", (async () => { throw new Error("down"); }) as unknown as typeof fetch)).toBe(false);
    expect(await walkthroughOn(undefined)).toBe(false);
    for (const p of ["app/page.tsx", "app/discover/page.tsx", "app/build/page.tsx", "components/NavLinks.tsx"]) {
      expect(read(p), p).not.toMatch(/\/ivy\/(?:desk|trades|picks)|Ivy's Desk|Ivy's Trades|From the ledger/);
    }
  });
});
