import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import type { LegendItem } from "../encodings/types";
import { PAYOFF_CHART_ENCODING, payoffChartLegend, payoffMark } from "../encodings/payoffChart";
import { EARNINGS_MARKER_ENCODING, earningsMarkerColor, earningsMarkerLegend } from "../encodings/earningsMarkers";
import { RV_TIER_ENCODING, rvTier, rvTierLegend } from "../encodings/rvTier";
import { VOL_REGIME_ENCODING, volRegime, volRegimeLegend } from "../encodings/volRegime";
import { EARNINGS_PROXIMITY_ENCODING, earningsProximity, earningsProximityLegend, earningsProximityText } from "../encodings/earningsProximity";
import { PICK_MOVE_ENCODING, PICK_RESULT_ENCODING, pickMove, pickResult, pickResultLegend } from "../encodings/pickResult";
import { MARK_BASIS_LABELS, markBasisLegend } from "../marks";
import { rvRankShort } from "../utils";
import { DISCOVER_IV_CHEAP_PP, DISCOVER_IV_RICH_PP, RV_RANK_ELEVATED, RV_RANK_EXTREME, RV_RANK_NORMAL } from "../thresholds";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

function expectLegendCovers(legend: LegendItem[], keys: string[]) {
  expect(legend.map((l) => l.key).sort()).toEqual([...keys].sort());
  for (const l of legend) expect(l.label.length).toBeGreaterThan(0);
}

describe("payoff chart", () => {
  it("has one legend row per mark, and the swatch is the mark", () => {
    const legend = payoffChartLegend();
    expectLegendCovers(legend, Object.keys(PAYOFF_CHART_ENCODING));
    for (const l of legend) {
      const mark = payoffMark(l.key as keyof typeof PAYOFF_CHART_ENCODING);
      expect(l.swatch.color).toBe(mark.stroke);
      expect(l.swatch.dashed).toBe(mark.strokeDasharray !== undefined);
    }
  });
  it("marks are distinguishable", () => {
    const sigs = Object.values(PAYOFF_CHART_ENCODING).map((m) => `${m.color}|${m.dash}`);
    expect(new Set(sigs).size).toBe(sigs.length);
  });
  it("the simulator draws from the config and renders the legend", () => {
    const src = read("components/PayoffSimulator.tsx");
    expect(src).toContain("payoffChartLegend()");
    for (const key of ["profit", "loss", "current", "scrubber", "zero"]) expect(src).toContain(`payoffMark("${key}")`);
    expect(src).not.toMatch(/stroke="hsl\(var\(--(success|destructive|cool)\)\)"/);
  });
});

describe("price-chart earnings markers", () => {
  it("has one swatch per distinct look and names every outcome", () => {
    const legend = earningsMarkerLegend();
    const looks = new Set(Object.values(EARNINGS_MARKER_ENCODING).map((v) => v.color));
    expect(legend.length).toBe(looks.size);
    const text = legend.map((l) => l.label).join(" ");
    for (const v of Object.values(EARNINGS_MARKER_ENCODING)) expect(text).toContain(v.label);
    for (const l of legend) { expect(l.swatch.kind).toBe("line"); expect(l.swatch.dashed).toBe(true); }
  });
  it("unknown outcomes fall back to the no-data color", () => {
    expect(earningsMarkerColor("something_new")).toBe(EARNINGS_MARKER_ENCODING.unknown.color);
  });
  it("the ticker page has no hand-written marker colors or legend text", () => {
    const src = read("app/tickers/[symbol]/page.tsx");
    expect(src).not.toContain("OUTCOME_DOT_COLOR");
    expect(src).not.toContain("green = beat");
    expect(src).toContain("earningsMarkerLegend()");
  });
});

describe("RV tier", () => {
  it("cutoffs come from the mirrored thresholds", () => {
    expect(rvTier(RV_RANK_NORMAL - 0.1).key).toBe("quiet");
    expect(rvTier(RV_RANK_NORMAL).key).toBe("normal");
    expect(rvTier(RV_RANK_ELEVATED).key).toBe("elevated");
    expect(rvTier(RV_RANK_EXTREME - 0.1).key).toBe("elevated");
    expect(rvTier(RV_RANK_EXTREME).key).toBe("extreme");
  });
  it("one function serves the watchlist, Build and discover", () => {
    expect(rvRankShort(92).tag).toBe(rvTier(92).label);
    expect(read("app/discover/page.tsx")).toContain("rvTier(item.rv_rank).label");
    expect(read("app/discover/page.tsx")).not.toContain("item.tier}");
    expect(read("lib/utils.ts")).not.toMatch(/rank < (25|70|90)/);
  });
  it("legend covers every tier and states its rule", () => {
    expectLegendCovers(rvTierLegend(), Object.keys(RV_TIER_ENCODING));
    expect(rvTierLegend().find((l) => l.key === "extreme")!.label).toContain(String(RV_RANK_EXTREME));
  });
});

describe("vol regime", () => {
  it("rules quote the thresholds, and cheap is not the up/beat green", () => {
    expect(VOL_REGIME_ENCODING.iv_rich.rule).toContain(String(DISCOVER_IV_RICH_PP));
    expect(VOL_REGIME_ENCODING.iv_cheap.rule).toContain(String(Math.abs(DISCOVER_IV_CHEAP_PP)));
    expect(VOL_REGIME_ENCODING.iv_cheap.className).not.toMatch(/success|green|emerald/);
  });
  it("legend covers every regime; unknown keys render nothing", () => {
    expectLegendCovers(volRegimeLegend(), Object.keys(VOL_REGIME_ENCODING));
    expect(volRegime("nonsense")).toBeNull();
    expect(volRegime(null)).toBeNull();
  });
  it("cards, Build and My Trades all use it", () => {
    for (const p of ["components/DiscoverCard.tsx", "app/build/page.tsx", "app/theses/page.tsx"]) {
      const src = read(p);
      expect(src, p).toMatch(/volRegime/);
      expect(src, p).not.toMatch(/"IV Rich"|>\s*IV Rich\s*<|IV Cheap\s*</);
    }
  });
});

describe("earnings proximity", () => {
  it("one scale, and a past date gets no tag", () => {
    expect(earningsProximity(0)!.key).toBe("imminent");
    expect(earningsProximity(1)!.key).toBe("imminent");
    expect(earningsProximity(3)!.key).toBe("soon");
    expect(earningsProximity(4)!.key).toBe("later");
    expect(earningsProximity(-2)).toBeNull();
    expect(earningsProximityText(0)).toBe("EPS today");
    expect(earningsProximityText(5)).toBe("EPS in 5d");
  });
  it("discover and the watchlist share it; the watchlist never says 'ago'", () => {
    expect(read("app/discover/page.tsx")).toContain("earningsProximity(");
    const wl = read("app/watchlist/page.tsx");
    expect(wl).toContain("earningsProximity(");
    const start = wl.indexOf("function nextEarningsLabel(");
    const fn = wl.slice(start, wl.indexOf("\n}\n", start));
    expect(fn.length).toBeGreaterThan(50);
    expect(fn).not.toContain("ago");   // a past date is not a next earnings date
  });
  it("legend covers every tier", () => {
    expectLegendCovers(earningsProximityLegend(), Object.keys(EARNINGS_PROXIMITY_ENCODING));
  });
});

describe("pick result", () => {
  it("HIT/MISS says it is about direction, and move color is about favor, not sign", () => {
    expect(pickResult(true)!.label).toBe("Direction HIT");
    expect(pickResult(null)).toBeNull();
    expect(pickMove("bearish", -3).key).toBe("favorable");
    expect(pickMove("bearish", 3).key).toBe("unfavorable");
    expect(pickMove("bullish", 3).key).toBe("favorable");
    expect(pickMove("bullish", 0).key).toBe("flat");
  });
  it("legend covers both results and both move colors, and the trades page renders it", () => {
    const keys = pickResultLegend().map((l) => l.key);
    expect(keys).toEqual([...Object.keys(PICK_RESULT_ENCODING), "favorable", "unfavorable"]);
    expect(Object.keys(PICK_MOVE_ENCODING)).toContain("flat");
    expect(read("app/ivy/trades/page.tsx")).toContain("pickResultLegend()");
  });
});

describe("mark basis", () => {
  it("legend covers every basis that is a mark", () => {
    expectLegendCovers(markBasisLegend(), Object.keys(MARK_BASIS_LABELS).filter((k) => k !== "no_option_leg"));
  });
});
