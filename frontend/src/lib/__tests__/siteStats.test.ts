/** The counters' three layers (lib/siteStats): what shows when the stats endpoint is slow, restarting or down. */
import { describe, expect, it } from "vitest";
import type { SiteStats } from "@/lib/api";
import { isSiteStats, pickStats, readSnapshot, SNAPSHOT_KEY, writeSnapshot } from "@/lib/siteStats";
import { COUNTER_LABELS, counterRows } from "@/lib/siteCounters";

const STATS: SiteStats = { option_contracts_captured: 116327, option_contracts_as_of: "2026-10-06", option_contracts_source: "courier chains", licensed_daily_prices: 666352,
  licensed_daily_prices_as_of: "2026-10-06", earnings_reports_measured: 9923, earnings_reports_as_of: "2026-09-29", analyst_reactions_measured: 9803, analyst_reactions_as_of: "2026-09-28" };

function fakeStorage(initial: Record<string, string> = {}) {
  const m = new Map(Object.entries(initial));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); }, map: m };
}

describe("the counters' layers", () => {
  it("fresh over server over stored, and nothing only when every layer is empty", () => {
    const stored = { stats: STATS, fetched_at: "2026-10-07T18:00:00Z" };
    expect(pickStats(STATS, null, null).source).toBe("fresh");
    expect(pickStats(null, STATS, stored).source).toBe("server");
    expect(pickStats(null, null, stored)).toEqual({ stats: STATS, source: "stored" });
    expect(pickStats(null, null, null)).toEqual({ stats: null, source: null });
  });

  it("the stored snapshot round-trips, and never throws on junk or blocked storage", () => {
    const s = fakeStorage();
    writeSnapshot(s, STATS, new Date("2026-10-07T18:00:00Z"));
    expect(readSnapshot(s)).toEqual({ stats: STATS, fetched_at: "2026-10-07T18:00:00.000Z" });
    expect(readSnapshot(fakeStorage({ [SNAPSHOT_KEY]: "{not json" }))).toBeNull();
    expect(readSnapshot(fakeStorage({ [SNAPSHOT_KEY]: JSON.stringify({ stats: { option_contracts_captured: "many" }, fetched_at: "x" }) }))).toBeNull();
    expect(readSnapshot(null)).toBeNull();
    const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(readSnapshot(broken)).toBeNull();
    expect(() => writeSnapshot(broken, STATS)).not.toThrow();
    expect(isSiteStats(STATS) && !isSiteStats({}) && !isSiteStats(null)).toBe(true);
  });

  it("the four labels exist without any count, and the rows use the same labels", () => {
    expect(COUNTER_LABELS.map((l) => l.label)).toEqual(["option contracts captured nightly", "daily stock prices on record", "earnings reactions measured", "analyst actions measured"]);
    expect(counterRows(STATS).map((r) => r.label)).toEqual(COUNTER_LABELS.map((l) => l.label));
  });
});
