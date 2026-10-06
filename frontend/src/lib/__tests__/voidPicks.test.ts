import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { IVY_OUTCOME_LABELS } from "@/lib/ivyOutcomes";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

describe("void picks stay in the ledger with their reason and outside every count", () => {
  it("the trades page counts only open and closed picks and lists void ones with the reason", () => {
    const page = read("app/ivy/trades/page.tsx");
    expect(page).toContain('const openPicks = picks.filter((p) => p.status === "open");');
    expect(page).toContain('const closedPicks = picks.filter((p) => p.status === "closed");');
    expect(page).toContain('const voidPicks = picks.filter((p) => p.status === "void");');
    expect(page).toContain("{p.void_reason && <p");
    expect(page).toContain("counted in nothing above, never deleted");
    expect(page).not.toMatch(/voidPicks\.(reduce|map\(\(p\) => p\.option_pnl)/);           // no P&L drawn from them
  });

  it("the unconfirmed-date outcome has a label", () => {
    expect(IVY_OUTCOME_LABELS.unconfirmed_date).toBe("Refused: report date not confirmed by the company");
  });
});
