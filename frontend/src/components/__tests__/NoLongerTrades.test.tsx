/** A stock that no longer trades with no successor: the page shows its stored line and, only when one is stored, the last close
 * with that close's own date; the trade builder, market value, catalysts, earnings line and Ask Ivy never render. */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { NoLongerTrades, longDate } from "@/components/ticker/NoLongerTrades";

const EA = { symbol: "EA", name: "Electronic Arts Inc." };
const LINE = "Electronic Arts was taken private on Aug 4, 2026, and its stock no longer trades.";

describe("NoLongerTrades", () => {
  it("shows the line and no close when none is stored", () => {
    const html = renderToStaticMarkup(<NoLongerTrades ticker={EA} exit={{ kind: "taken_private", line: LINE, since: "2026-08-04", last_close: null, last_close_date: null }} />);
    expect(html).toContain(LINE);
    expect(html).not.toContain("exit-last-close");
    for (const gone of ["Build a trade", "Catalysts", "Ask", "earnings", "$"]) expect(html).not.toContain(gone);
  });

  it("shows the last stored close with its own date when one is stored", () => {
    const html = renderToStaticMarkup(<NoLongerTrades ticker={EA} exit={{ kind: "taken_private", line: LINE, since: "2026-08-04", last_close: 197.5, last_close_date: "2026-08-04" }} />);
    expect(html).toContain("Last stored close $197.50 on Aug 4, 2026");
  });

  it("reads a date from its own parts", () => {
    expect(longDate("2026-08-04")).toBe("Aug 4, 2026");
    expect(longDate("2026-01-01")).toBe("Jan 1, 2026");
  });

  it("the ticker page returns this view before the trade builder, market value, earnings line or question strip", () => {
    const src = readFileSync(join(__dirname, "../../app/tickers/[symbol]/page.tsx"), "utf8");
    const at = src.indexOf("if (ticker.exit) return <NoLongerTrades");
    expect(at).toBeGreaterThan(0);
    for (const later of ["Build a trade on {ticker.symbol}", "formatMarketCap(ticker.market_cap)", 'data-testid="next-earnings-line"', "<QuestionStrip", 'label="Catalysts"'])
      expect(src.indexOf(later)).toBeGreaterThan(at);
  });
});
