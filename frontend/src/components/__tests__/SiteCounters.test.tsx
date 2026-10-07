/** The home page renders the four counters when the stats endpoint fails: from the server's values when it has them, and as the
 * four labels with a dash each when it has nothing, never as an empty section. */
import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { SiteStats } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: { system: { stats: () => Promise.reject(new Error("backend restarting")) } } }));

const STATS: SiteStats = { option_contracts_captured: 116327, option_contracts_as_of: "2026-10-06", option_contracts_source: "courier chains", licensed_daily_prices: 666352,
  licensed_daily_prices_as_of: "2026-10-06", earnings_reports_measured: 9923, earnings_reports_as_of: "2026-09-29", analyst_reactions_measured: 9803, analyst_reactions_as_of: "2026-09-28" };
const LABELS = ["option contracts captured nightly", "daily stock prices on record", "earnings reactions measured", "analyst actions measured"];

describe("SiteCounters with the stats endpoint failing", () => {
  it("renders the server's four counts with their as-of dates", async () => {
    const { SiteCounters } = await import("@/components/SiteCounters");
    const html = renderToStaticMarkup(<SiteCounters initial={STATS} />);
    for (const n of ["116,327", "666,352", "9,923", "9,803"]) expect(html).toContain(n);
    for (const l of LABELS) expect(html).toContain(l);
    expect(html).toContain("As of Oct 6, 2026 (courier chains)");
    expect(html).not.toContain('data-counters="unavailable"');
  });

  it("renders the four labels with a dash each when it has no count at all, never nothing", async () => {
    const { SiteCounters } = await import("@/components/SiteCounters");
    const html = renderToStaticMarkup(<SiteCounters initial={null} />);
    expect(html).toContain('data-counters="unavailable"');
    for (const l of LABELS) expect(html).toContain(l);
    expect(html.split("—").length - 1).toBe(4);
    expect(html).toContain("Counts not available right now");
    expect(html.length).toBeGreaterThan(200);
  });
});
