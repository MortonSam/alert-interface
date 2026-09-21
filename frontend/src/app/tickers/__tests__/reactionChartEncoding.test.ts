import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import type { EarningsOutcome } from "@/lib/api";
import { REACTION_CHART_ENCODING, barCellStyle, legendEntries } from "../[symbol]/reactionChartEncoding";

const OUTCOMES: EarningsOutcome[] = ["beat", "miss", "meet", "unknown"];
const PCTS = [2.5, 0, -2.5];

function stylesInUse(isFed: boolean) {
  return OUTCOMES.flatMap((o) => PCTS.map((p) => barCellStyle(p, o, isFed)));
}

describe("reaction chart legend matches bar styling", () => {
  it("every bar style has a legend entry that describes it", () => {
    const legend = legendEntries(false);
    for (const s of stylesInUse(false)) {
      const dir = legend.find((e) => e.kind === "direction" && e.key === s.directionKey);
      expect(dir, `no legend entry for direction ${s.directionKey}`).toBeDefined();
      expect(dir!.kind === "direction" && dir!.color).toBe(s.fill);

      const out = legend.find((e) => e.kind === "outcome" && e.key === s.outcomeKey);
      expect(out, `no legend entry for outcome style ${s.outcomeKey}`).toBeDefined();
      if (out!.kind !== "outcome") throw new Error("unreachable");
      expect(out!.fillOpacity).toBe(s.fillOpacity);
      expect(out!.dashed).toBe(s.strokeDasharray !== "");
    }
  });

  it("every legend entry has a bar style that uses it", () => {
    const used = stylesInUse(false);
    for (const e of legendEntries(false)) {
      const match = used.some((s) => (e.kind === "direction" ? s.directionKey === e.key : s.outcomeKey === e.key));
      expect(match, `legend entry "${e.label}" matches no bar style`).toBe(true);
    }
  });

  it("outcome styles are visually distinct from each other", () => {
    const sigs = Object.values(REACTION_CHART_ENCODING.outcome).map((o) => `${o.fillOpacity}|${o.dashed}`);
    expect(new Set(sigs).size).toBe(sigs.length);
  });

  it("fed mode encodes direction only, and its legend says only that", () => {
    expect(legendEntries(true).every((e) => e.kind === "direction")).toBe(true);
    for (const s of stylesInUse(true)) {
      expect(s.outcomeKey).toBeNull();
      expect(s.fillOpacity).toBe(1.0);
      expect(s.strokeDasharray).toBe("");
    }
  });

  it("color never encodes outcome: a beat that falls is the down color, a miss that rises is the up color", () => {
    expect(barCellStyle(-5, "beat", false).fill).toBe(REACTION_CHART_ENCODING.direction.down.color);
    expect(barCellStyle(3, "miss", false).fill).toBe(REACTION_CHART_ENCODING.direction.up.color);
  });

  it("ReactionChart reads styling from the config, not hardcoded values", () => {
    const src = readFileSync(join(__dirname, "../[symbol]/page.tsx"), "utf8");
    const start = src.indexOf("function ReactionChart(");
    const chart = src.slice(start, src.indexOf("\n}\n", start));
    expect(chart).toContain("barCellStyle(");
    expect(chart).toContain("legendEntries(");
    expect(chart).not.toMatch(/#22c55e|#ef4444|fillOpacity=|strokeDasharray="3 2"|> Beat<|> Miss</);
  });
});
