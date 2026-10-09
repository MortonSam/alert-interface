import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { QUOTE_BASIS_LABELS, quoteAsOf } from "@/lib/freshness";

describe("a quote names what its time marks", () => {
  it("every basis the API sends has a label, the same as the backend's", () => {
    const py = readFileSync(join(__dirname, "../../../../backend/app/services/quote_fallback.py"), "utf8");
    const m = py.match(/BASIS_LABELS = \{([^}]*)\}/)?.[1] ?? "";
    const keys = Object.fromEntries([...m.matchAll(/TRADE_BASIS|CLOSE_BASIS/g)].map((k) => [k[0], true]));
    expect(Object.keys(keys).sort()).toEqual(["CLOSE_BASIS", "TRADE_BASIS"]);
    expect(py).toContain('TRADE_BASIS, CLOSE_BASIS = "last_trade", "close"');
    expect(py).toContain('{TRADE_BASIS: "last trade", CLOSE_BASIS: "close"}');
    expect(QUOTE_BASIS_LABELS).toEqual({ last_trade: "last trade", close: "close" });
  });

  it("a stored close is dated by its session and named a close; a last trade carries its date and time", () => {
    const closeAt = Date.UTC(2026, 9, 8, 20, 0) / 1000;                 // Oct 8, 4:00 PM New York
    expect(quoteAsOf(closeAt, "close")).toBe("Oct 8, 4:00 PM ET close");
    expect(quoteAsOf(closeAt, "last_trade")).toBe("Oct 8, 4:00 PM ET");
    expect(quoteAsOf(null, "close")).toBeNull();
  });
});
