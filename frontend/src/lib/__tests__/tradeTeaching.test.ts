import { describe, expect, it } from "vitest";
import { classify, payoffAt, teachPanel, type TeachLeg } from "@/lib/tradeTeaching";
import { LINES, REGIONS, RESULT, STRUCTURES } from "@/lib/tradeTeachingCopy";

// the five trades of docs/build_a_trade_wording.md (BNY's from Sam's screenshot; the other prices illustrative)
export const EXAMPLES: { title: string; symbol: string; expiration: string; legs: TeachLeg[] }[] = [
  { title: "BNY $145/$155 call spread", symbol: "BNY", expiration: "2026-11-20",
    legs: [{ type: "call", side: "long", strike: 145, price: 5.2 }, { type: "call", side: "short", strike: 155, price: 1.6 }] },
  { title: "NVDA $220 call", symbol: "NVDA", expiration: "2026-12-18", legs: [{ type: "call", side: "long", strike: 220, price: 8.4 }] },
  { title: "KO $90/$85 put credit spread", symbol: "KO", expiration: "2026-12-18",
    legs: [{ type: "put", side: "short", strike: 90, price: 2.1 }, { type: "put", side: "long", strike: 85, price: 0.7 }] },
  { title: "TSLA $450 straddle", symbol: "TSLA", expiration: "2026-11-20",
    legs: [{ type: "call", side: "long", strike: 450, price: 22 }, { type: "put", side: "long", strike: 450, price: 20.5 }] },
  { title: "AAPL $285 covered call", symbol: "AAPL", expiration: "2026-12-18",
    legs: [{ type: "stock", side: "long", price: 270 }, { type: "call", side: "short", strike: 285, price: 3.1 }] },
];

describe("What this trade does, from the trade's own legs", () => {
  it("names each structure Build a Trade can hold", () => {
    expect(EXAMPLES.map((e) => classify(e.legs))).toEqual(["call_debit_spread", "call", "put_credit_spread", "straddle", "covered_call"]);
    expect(classify([{ type: "put", side: "long", strike: 100, price: 3 }])).toBe("put");
    expect(classify([{ type: "put", side: "long", strike: 100, price: 6 }, { type: "put", side: "short", strike: 90, price: 2 }])).toBe("put_debit_spread");
    expect(classify([{ type: "call", side: "short", strike: 100, price: 4 }, { type: "call", side: "long", strike: 110, price: 1 }])).toBe("call_credit_spread");
    expect(classify([{ type: "call", side: "long", strike: 110, price: 2 }, { type: "put", side: "long", strike: 90, price: 2 }])).toBe("strangle");
    expect(classify([{ type: "stock", side: "long", price: 100 }, { type: "put", side: "long", strike: 95, price: 2 }])).toBe("protective_put");
  });

  it("states BNY's call spread in its own figures", () => {
    const p = teachPanel("BNY", EXAMPLES[0].legs, "2026-11-20");
    expect(p.lines).toEqual([
      LINES.intro(STRUCTURES.call_debit_spread.name, STRUCTURES.call_debit_spread.explain),
      "You pay $360 at the start: a net debit of $3.60 a share, for 100 shares.",
      "It gains if BNY ends above $148.60 at expiration on Nov 20, 2026.",
      "The breakeven is $148.60: the $145 strike price plus the $3.60 a share paid.",
      "The gain stops growing at $155: past it, the most the trade can make is $640.",
      "The most it can lose is $360, the amount paid.",
    ]);
    expect(p.expirationLine).toBe("At expiration on Nov 20, 2026:");
    expect(p.regions).toEqual([
      "Above $155: a $640 gain, wherever it ends in that range.",
      "Between $145 and $155: the result grows by $100 for every $1 the stock rises, from a $360 loss at $145 to a $640 gain at $155.",
      "Below $145: a $360 loss, wherever it ends in that range.",
    ]);
  });

  it("states a single call, a put credit spread, a straddle and a covered call", () => {
    const call = teachPanel("NVDA", EXAMPLES[1].legs, "2026-12-18");
    expect(call.lines.slice(1)).toEqual(["You pay $840 at the start: $8.40 a share, for 100 shares.", "It gains if NVDA ends above $228.40 at expiration on Dec 18, 2026.",
      "The breakeven is $228.40: the $220 strike price plus the $8.40 a share paid.", LINES.noCapUp, "The most it can lose is $840, the amount paid."]);
    expect(call.regions).toEqual(["Above $220: the result grows by $100 for every $1 the stock rises past $220, from an $840 loss there.",
      "Below $220: an $840 loss, wherever it ends in that range."]);
    const credit = teachPanel("KO", EXAMPLES[2].legs, "2026-12-18");
    expect(credit.lines.slice(1)).toEqual(["You receive $140 at the start: a net credit of $1.40 a share, for 100 shares.",
      "It gains if KO ends above $88.60 at expiration on Dec 18, 2026.", "The breakeven is $88.60: the $90 strike price minus the $1.40 a share received.",
      "The gain stops growing at $90: past it, the most the trade can make is $140.", "The most it can lose is $360, if it ends at or below $85."]);
    const straddle = teachPanel("TSLA", EXAMPLES[3].legs, "2026-11-20");
    expect(straddle.lines.slice(1)).toEqual(["You pay $4,250 at the start: a net debit of $42.50 a share, for 100 shares.",
      "It gains if TSLA ends below $407.50 or above $492.50 at expiration on Nov 20, 2026: a big enough move either way.",
      "There are two breakevens, $407.50 and $492.50: the result at expiration is zero at each.",
      "There is no cap on the gain as the stock rises; as it falls, the gain grows up to $40,750 if it reached $0.", "The most it can lose is $4,250, the amount paid."]);
    const covered = teachPanel("AAPL", EXAMPLES[4].legs, "2026-12-18");
    expect(covered.lines.slice(1)).toEqual(["You receive $310 at the start: a net credit of $3.10 a share, for 100 shares.", "It assumes 100 shares held at $270.",
      "It gains if AAPL ends above $266.90 at expiration on Dec 18, 2026.", "The breakeven is $266.90: the $270 share price minus the $3.10 a share received.",
      "The gain stops growing at $285: past it, the most the trade can make is $1,810.", "The most it can lose is $26,690, if it ends at $0."]);
  });

  it("every figure the panel states is the payoff at expiration of the legs", () => {
    for (const e of EXAMPLES) {
      const p = teachPanel(e.symbol, e.legs, e.expiration);
      for (const m of [...p.lines, ...p.regions].join(" ").matchAll(/(a|an) \$([\d,]+) (gain|loss) at \$([\d.]+)/g)) {
        const v = payoffAt(e.legs, Number(m[4]));
        expect(Math.round(Math.abs(v))).toBe(Number(m[2].replace(/,/g, "")));
        expect(v >= 0).toBe(m[3] === "gain");
      }
    }
  });

  it("says nothing that tells anyone to buy or sell", () => {
    const all = EXAMPLES.flatMap((e) => { const p = teachPanel(e.symbol, e.legs, e.expiration); return [...p.lines, p.expirationLine, ...p.regions]; });
    for (const s of all) expect(s).not.toMatch(/\b(you should|consider (buying|selling)|buy now|sell now|good (buy|time)|recommend|worth (buying|selling))\b/i);
    expect(RESULT.zero).toBe("no gain or loss");
    expect(REGIONS.above("$1")).toBe("Above $1");
  });
});

describe("each term is explained at its first use in the panel only", () => {
  it("keeps the first strike price, net debit, expiration and breakeven and leaves the later ones plain", async () => {
    const { firstUses } = await import("@/components/TradeTeachingPanel");
    const p = teachPanel("BNY", EXAMPLES[0].legs, "2026-11-20");
    const keyed = firstUses([...p.lines, p.expirationLine, ...p.regions]).flat().filter((s) => s.key).map((s) => s.key);
    expect(keyed).toEqual([...new Set(keyed)]);                       // no term twice
    expect(keyed).toEqual(expect.arrayContaining(["strike", "net-debit", "expiration", "breakeven"]));
    const credit = teachPanel("KO", EXAMPLES[2].legs, "2026-12-18");
    expect(firstUses(credit.lines).flat().some((s) => s.key === "net-credit")).toBe(true);
  });
});
