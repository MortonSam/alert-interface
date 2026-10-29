// A report's 3- and 5-day moves fill in after its first-day move (Sam, 2026-10-29): a window still to close reads "Not yet
// available", never a zero and never "Not on file".
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { HistoricalReaction } from "@/lib/api";
import { MOVE_NOT_ON_FILE, MOVE_NOT_YET, reportCard } from "@/lib/reportCards";

const row = (over: Partial<HistoricalReaction>): HistoricalReaction => ({
  id: "r1", ticker_id: "t", event_id: null, event_type: "earnings", event_date: "2026-10-28", close_before: null, open_after: null,
  close_after: null, pct_change_1d: "4.2", pct_change_3d: null, pct_change_5d: null, volume_before: null, volume_after: null, notes: null,
  eps_estimate: null, eps_actual: null, revenue_estimate: null, revenue_actual: null, outcome: "unknown", ...over,
} as HistoricalReaction);

describe("longer windows still to close", () => {
  it("a report on Oct 28 after the close: the first-day move shows, the 3- and 5-day moves are pending, not zero", () => {
    const c = reportCard(row({ pending_windows: ["3d", "5d"] }));
    expect(c.moves[0]).toMatchObject({ key: "1d", value: 4.2 });
    expect(c.moves[1]).toMatchObject({ key: "3d", value: null, pending: true });
    expect(c.moves[2]).toMatchObject({ key: "5d", value: null, pending: true });
  });
  it("an old empty window is not on file, not pending", () => {
    const c = reportCard(row({ event_date: "2025-01-10" }));
    expect(c.moves[2]).toMatchObject({ value: null, pending: false });
  });
  it("the card renders each state in words", () => {
    const src = readFileSync(join(__dirname, "../../components/ticker/ReportCards.tsx"), "utf8");
    expect(src).toContain("m.value == null ? (m.pending ? MOVE_NOT_YET : MOVE_NOT_ON_FILE) : fmtMove(m.value)");
    expect(MOVE_NOT_YET).toBe("Not yet available");
    expect(MOVE_NOT_ON_FILE).toBe("Not on file");
  });
});
