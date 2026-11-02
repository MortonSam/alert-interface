import { describe, expect, it } from "vitest";
import { liveParts, liveReceipt, pendingFilingLabel, writtenLabel } from "@/lib/liveFigures";

const inputs = [
  { name: "last close", value: "$215.38", as_of: "2026-10-30", source: "price_bars_shadow" },
  { name: "P/E", value: "27.2", as_of: "2026-10-30", source: "pe_snapshots" },
  { name: "price against the 52-week high", value: "below", as_of: "2026-10-06", source: null },
];

describe("a note's live figures", () => {
  it("marks each filled figure with its receipt's name and as-of date", () => {
    const parts = liveParts("NVIDIA closed at $215.38, with a P/E of 27.2.", inputs);
    expect(parts.map((p) => p.text).join("")).toBe("NVIDIA closed at $215.38, with a P/E of 27.2.");
    expect(parts.filter((p) => p.tip).map((p) => [p.text, p.tip])).toEqual([
      ["$215.38", "last close, as of Oct 30, 2026"],
      ["27.2", "P/E, as of Oct 30, 2026"],
    ]);
  });

  it("leaves text without live figures whole", () => {
    expect(liveParts("Revenue rose 105.9% from a year earlier.", inputs)).toEqual([{ text: "Revenue rose 105.9% from a year earlier." }]);
    expect(liveParts("Revenue rose.", [])).toEqual([{ text: "Revenue rose." }]);
  });

  it("matches the longest value first", () => {
    const parts = liveParts("Closed at $215.38.", [{ name: "x", value: "$215", as_of: null, source: null }, inputs[0]]);
    expect(parts.find((p) => p.tip)?.text).toBe("$215.38");
  });

  it("names a receipt with no date by its name alone", () => {
    expect(liveReceipt({ name: "P/E", value: "27.2", as_of: null, source: null })).toBe("P/E");
  });

  it("states the note's written date and a newer filing without promising when it is read", () => {
    expect(writtenLabel("2026-10-30T08:57:59Z")).toBe("Written Oct 30, 2026");
    expect(pendingFilingLabel({ form: "8-K", filed_on: "2026-11-02" })).toBe("Not yet in this note: the 8-K filed Nov 2, 2026");
    expect(pendingFilingLabel(null)).toBeNull();
  });
});
