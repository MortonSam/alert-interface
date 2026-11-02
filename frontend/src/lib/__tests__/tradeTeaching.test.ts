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
      "You pay $360 at the start, a net debit of $3.60 a share, for 100 shares.",
      LINES.optionUnit,
      "It gains if BNY ends above $148.60 at expiration on Nov 20, 2026.",
      "The breakeven is $148.60, the $145 strike price plus the $3.60 a share paid.",
      "The gain stops growing at $155. Past it, the most the trade can make is $640.",
      "The most it can lose is $360, the amount paid.",
    ]);
    expect(p.expirationLine).toBe("At expiration on Nov 20, 2026");
    expect(p.regions).toEqual([
      "Above $155, a $640 gain, wherever it ends in that range.",
      "Between $148.60 and $155, the gain grows by $100 for every $1 higher, up to $640 at $155.",
      "Between $145 and $148.60, a loss that shrinks as the stock rises, largest at $145 ($360).",
      "Below $145, a $360 loss, wherever it ends in that range.",
    ]);
    expect(p.closing).toBe("You don't have to wait for expiration. You can close the trade earlier at whatever it's worth that day.");
  });

  it("states a single call, a put credit spread, a straddle and a covered call", () => {
    const call = teachPanel("NVDA", EXAMPLES[1].legs, "2026-12-18");
    expect(call.lines.slice(1)).toEqual(["You pay $840 at the start, $8.40 a share, for 100 shares.", LINES.optionUnit,
      "It gains if NVDA ends above $228.40 at expiration on Dec 18, 2026.",
      "The breakeven is $228.40, the $220 strike price plus the $8.40 a share paid.", LINES.noCapUp, "The most it can lose is $840, the amount paid."]);
    expect(call.regions).toEqual(["Above $228.40, the gain grows by $100 for every $1 higher.",
      "Between $220 and $228.40, a loss that shrinks as the stock rises, largest at $220 ($840).",
      "Below $220, an $840 loss, wherever it ends in that range."]);
    const credit = teachPanel("KO", EXAMPLES[2].legs, "2026-12-18");
    expect(credit.lines.slice(1)).toEqual(["You receive $140 at the start, a net credit of $1.40 a share, for 100 shares.", LINES.optionUnit,
      "It gains if KO ends above $88.60 at expiration on Dec 18, 2026.", "The breakeven is $88.60, the $90 strike price minus the $1.40 a share received.",
      "You keep the full $140 if KO ends above $90.", "The most it can lose is $360, if it ends at or below $85."]);
    const straddle = teachPanel("TSLA", EXAMPLES[3].legs, "2026-11-20");
    expect(straddle.lines.slice(1)).toEqual(["You pay $4,250 at the start, a net debit of $42.50 a share, for 100 shares.", LINES.optionUnit,
      "It gains if TSLA ends below $407.50 or above $492.50 at expiration on Nov 20, 2026, a big enough move either way.",
      "There are two breakevens, $407.50 and $492.50, and the result at expiration is zero at each.",
      "There is no cap on the gain as the stock rises; as it falls, the gain grows up to $40,750 if it reached $0.", "The most it can lose is $4,250, the amount paid."]);
    expect(straddle.regions).toEqual(["Above $492.50, the gain grows by $100 for every $1 higher.",
      "Between $450 and $492.50, a loss that shrinks as the stock rises, largest at $450 ($4,250).",
      "Between $407.50 and $450, a loss that shrinks as the stock falls, largest at $450 ($4,250).",
      "Below $407.50, the gain grows by $100 for every $1 lower."]);
    const covered = teachPanel("AAPL", EXAMPLES[4].legs, "2026-12-18");
    expect(covered.lines).toEqual(["This is a covered call. You own 100 shares and sell someone the right to buy them from you at $285, which brings in cash now. If AAPL ends above $285, you sell at $285 and miss any rise past it.",
      "You receive $310 at the start, a net credit of $3.10 a share, for 100 shares.", LINES.optionUnit, "It assumes 100 shares held at $270.",
      "It gains if AAPL ends above $266.90 at expiration on Dec 18, 2026.", "The breakeven is $266.90, the $270 share price minus the $3.10 a share received.",
      "The most it can make is $1,810, if AAPL ends at or above $285.",
      "If AAPL fell to $0, you would lose $26,690, which is $310 less than owning the shares alone."]);
    expect(covered.regions[2]).toBe("Below $266.90, a loss that shrinks as the stock rises, largest at $0 ($26,690).");
  });

  it("a call credit spread keeps its credit below the lower strike", () => {
    const p = teachPanel("KO", [{ type: "call", side: "short", strike: 100, price: 4 }, { type: "call", side: "long", strike: 110, price: 1 }], "2026-12-18");
    expect(p.lines).toContain("You keep the full $300 if KO ends below $100.");
  });

  it("every breakeven bounds a stretch, each stretch is all gain or all loss, and no line has a colon", () => {
    const more: TeachLeg[][] = [
      [{ type: "put", side: "long", strike: 100, price: 3 }],
      [{ type: "put", side: "long", strike: 100, price: 6 }, { type: "put", side: "short", strike: 90, price: 2 }],
      [{ type: "call", side: "short", strike: 100, price: 4 }, { type: "call", side: "long", strike: 110, price: 1 }],
      [{ type: "call", side: "long", strike: 110, price: 2 }, { type: "put", side: "long", strike: 90, price: 2 }],
      [{ type: "stock", side: "long", price: 100 }, { type: "put", side: "long", strike: 95, price: 2 }],
    ];
    for (const legs of [...EXAMPLES.map((e) => e.legs), ...more]) {
      const p = teachPanel("KO", legs, "2026-12-18");
      for (const s of [...p.lines, p.expirationLine, ...p.regions, p.closing]) expect(s).not.toContain(":");
      expect(p.lines.filter((l) => l === LINES.optionUnit)).toHaveLength(1);
      const num = (x: string) => Number(x.replace(/,/g, ""));
      const stretches = p.regions.map((r) => r.match(/^(Above|Below|Between) \$([\d,]*\d(?:\.\d+)?)(?: and \$([\d,]*\d(?:\.\d+)?))?/)!);
      const bounds = new Set(stretches.flatMap((m) => [m[2], m[3]]).filter(Boolean));
      for (const m of stretches) {
        const [lo, hi] = m[1] === "Above" ? [num(m[2]), num(m[2]) + 1000] : m[1] === "Below" ? [0, num(m[2])] : [num(m[2]), num(m[3])];
        const ends = [payoffAt(legs, lo), payoffAt(legs, hi)].map(Math.round);
        expect(Math.min(...ends) < 0 && Math.max(...ends) > 0).toBe(false);
      }
      for (const m of p.lines.join(" ").matchAll(/breakevens?(?: is|, ) ?\$([\d.]+)(?: and \$([\d.]+))?/g)) {
        for (const be of [m[1], m[2]].filter(Boolean)) expect(bounds).toContain(be);
      }
      expect(p.regions.join(" ")).not.toMatch(/drops by|for every \$1 the stock rises/);
    }
  });

  it("every figure the panel states is the payoff at expiration of the legs", () => {
    for (const e of EXAMPLES) {
      const p = teachPanel(e.symbol, e.legs, e.expiration);
      const text = [...p.lines, ...p.regions].join(" ");
      for (const m of text.matchAll(/up to \$([\d,]+) at \$([\d.]+)/g)) expect(Math.round(payoffAt(e.legs, Number(m[2])))).toBe(Number(m[1].replace(/,/g, "")));
      for (const m of text.matchAll(/largest at \$([\d.]+) \(\$([\d,]+)\)/g)) expect(Math.round(-payoffAt(e.legs, Number(m[1])))).toBe(Number(m[2].replace(/,/g, "")));
    }
  });

  it("says nothing that tells anyone to buy or sell", () => {
    const all = EXAMPLES.flatMap((e) => { const p = teachPanel(e.symbol, e.legs, e.expiration); return [...p.lines, p.expirationLine, ...p.regions, p.closing]; });
    for (const s of all) expect(s).not.toMatch(/\b(you should|consider (buying|selling)|buy now|sell now|good (buy|time)|recommend|worth (buying|selling))\b/i);
    expect(RESULT.zero).toBe("no gain or loss");
    expect(REGIONS.above("$1")).toBe("Above $1");
    expect(Object.values(STRUCTURES).map((x) => x.explain).join(" ")).not.toContain(":");
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
