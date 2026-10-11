import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { ThesisDraftRead } from "@/lib/api";
import { cheaperCostLine, expensiveOptionsLine, expensiveOptionsPrompt } from "@/lib/cheaperDraft";

const draft = { symbol: "PANW", options_expensive: { implied_pct: 13.4, usual_pct: 6.5, cap: 1.2, outright_strike: 300, outright_mid: 13, outright_kind: "call" } } as unknown as ThesisDraftRead;

describe("Build a Trade never dead-ends on expensive options", () => {
  it("says plainly why the draft is a spread and compares the two costs", () => {
    expect(expensiveOptionsLine("PANW")).toBe("The options on PANW are expensive right now compared with how much the stock usually moves, so the draft below is a cheaper way to make the same bet.");
    expect(cheaperCostLine(draft, 780)).toBe("This spread costs $780 per contract. Buying the $300 call outright would cost $1,300.");
    expect(cheaperCostLine(draft, null)).toBeNull();
    expect(cheaperCostLine({ ...draft, options_expensive: null }, 780)).toBeNull();
    expect(expensiveOptionsPrompt("PANW")).toContain("Pick a direction and the draft will be a cheaper way to make that bet.");
  });
  it("the page shows the line instead of a refusal, and the cheaper draft's comparison", () => {
    const page = readFileSync(join(__dirname, "../../app/build/page.tsx"), "utf8");
    expect(page).toContain('alertPick.outcome === "vol_gate" && (');
    expect(page).toContain("{expensiveOptionsPrompt(alertPick.symbol)}");
    expect(page).toContain('alertPick.outcome !== "picked" && alertPick.outcome !== "vol_gate" && (');   // no refusal box on expensive options
    expect(page).toContain("cheaperCostLine(draft, costPerContract)");
  });
});
