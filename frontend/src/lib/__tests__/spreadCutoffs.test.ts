// One set of IV-RV spread cutoffs (Sam's item 7, 2026-11-16): the ticker page's spread row and the vol regime chip word a spread by
// SPREAD_RICH_PP / SPREAD_CHEAP_PP, the draft rules' cutoffs (backend thresholds.vol_regime_key, mirrored by test_threshold_sync).
// The backend's tests/test_spread_cutoffs.py also fails on any second copy of the cutoffs in frontend/src.
import { describe, expect, it } from "vitest";
import { SPREAD_CHEAP_PP, SPREAD_RICH_PP } from "@/lib/thresholds";
import { spreadRowValue } from "@/lib/optionsRows";
import { VOL_REGIME_ENCODING } from "@/lib/encodings/volRegime";

// the chip's regime for a spread, as the backend's vol_regime_key assigns it
const regime = (x: number) => (x > SPREAD_RICH_PP ? "iv_rich" : x < SPREAD_CHEAP_PP ? "iv_cheap" : "iv_fair");
const rowWord = (x: number) => {
  const t = spreadRowValue(x, 0.3 + x / 100, 0.3);
  return t.endsWith("look pricey") ? "iv_rich" : t.endsWith("look cheap") ? "iv_cheap" : "iv_fair";
};

describe("spread cutoffs", () => {
  it("are the draft rules' +8 / -4", () => {
    expect([SPREAD_RICH_PP, SPREAD_CHEAP_PP]).toEqual([8, -4]);
  });

  it("word the ticker row as the chip is assigned, at and around every cutoff", () => {
    const probes = [-50, -12, -10, -7, 0, 9, 10, 12, 50, ...[SPREAD_CHEAP_PP, SPREAD_RICH_PP].flatMap((c) => [c - 0.1, c, c + 0.1])];
    for (const x of probes) expect(rowWord(x), `spread ${x}`).toBe(regime(x));
  });

  it("give the chip's rule examples from the same cutoffs", () => {
    expect(VOL_REGIME_ENCODING.iv_rich.rule).toContain(`over ${30 + SPREAD_RICH_PP}%`);
    expect(VOL_REGIME_ENCODING.iv_cheap.rule).toContain(`under ${30 + SPREAD_CHEAP_PP}%`);
    expect(VOL_REGIME_ENCODING.iv_fair.rule).toContain(`from ${30 + SPREAD_CHEAP_PP}% to ${30 + SPREAD_RICH_PP}%`);
  });
});
