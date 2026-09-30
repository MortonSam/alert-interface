import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import { ALTERNATIVE_FAILED, DESK_FAILED, DRAFT_FAILED, SAVE_FAILED, TRADES_FAILED, visitorMessage } from "@/lib/errors";
import { IVY_OUTCOME_LABELS, NO_DRAFT_NOT_CHARGED, ivyDecisionSentence } from "@/lib/ivyOutcomes";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

describe("Let Ivy decide without a draft", () => {
  it("names every outcome in one sentence, with the desk's own verb and reason", () => {
    expect(ivyDecisionSentence("AAPL", "vol_gate")).toBe("Ivy refused AAPL: options too expensive for the edge");
    expect(ivyDecisionSentence("AAPL", "no_fresh_chain")).toBe("Ivy refused AAPL: no current options data");
    expect(ivyDecisionSentence("AAPL", "structure_failed")).toBe("Ivy refused AAPL: could not build the spread from the available strikes");
    expect(ivyDecisionSentence("AAPL", "no_features")).toBe("Ivy passed on AAPL: no data for this name");
    expect(ivyDecisionSentence("AAPL", "momentum_gate")).toBe("Ivy passed on AAPL: no momentum setup");
    expect(ivyDecisionSentence("AAPL", "insufficient_history")).toBe("Ivy passed on AAPL: not enough earnings history");
    expect(ivyDecisionSentence("AAPL", "skipped")).toBe("Ivy passed on AAPL: no setup for this name");
    expect(ivyDecisionSentence("AAPL", "cap_reached")).toBe("Ivy passed on AAPL: pick limit reached");
    expect(ivyDecisionSentence("AAPL", "mixed_evidence")).toBe("Ivy passed on AAPL: signals disagreed (earlier engine)");
    expect(ivyDecisionSentence("AAPL", "open_pick_exists")).toBe("Ivy is holding AAPL: already has an open pick in this name");
    expect(ivyDecisionSentence("AAPL", "error")).toBe("Ivy could not evaluate AAPL: error during evaluation");
    expect(ivyDecisionSentence("AAPL", "picked")).toBe("Ivy picked AAPL.");
    // the label the API sends wins over the local table, so a new backend label reads right without a deploy
    expect(ivyDecisionSentence("AAPL", "vol_gate", "Refused: premium too rich")).toBe("Ivy refused AAPL: premium too rich");
    for (const outcome of Object.keys(IVY_OUTCOME_LABELS)) {
      expect(ivyDecisionSentence("X", outcome)).toMatch(/^Ivy /);
    }
    expect(NO_DRAFT_NOT_CHARGED).toContain("did not use one of your free drafts");
  });

  it("the page renders the sentence for any outcome without a draft, keeps the slot note, and drafts a pick once", () => {
    const src = read("app/build/page.tsx");
    expect(src).toContain("ivyDecisionSentence(alertPick.symbol, alertPick.outcome, alertPick.outcome_label)");
    expect(src).toContain('{NO_DRAFT_NOT_CHARGED} Pick a direction manually below.');
    expect(src).toMatch(/alertPick && !alertPick\.existing_pick && !alertPick\.draft && alertPick\.outcome !== "picked" && \(/);
    expect(src).toMatch(/const ivyDecided = !!alertPick && !alertPick\.draft && alertPick\.outcome !== "picked";/);
    expect(src).toMatch(/else if \(result\.outcome === "picked" && dir\) \{[\s\S]{0,300}await handleGenerate\(dir\);/);
    expect(src).not.toContain("mixed_evidence");   // no outcome is special-cased by name
    expect(src).not.toMatch(/setDraft\(null\);\s*setStep\("review_draft"\)/);
  });
});

describe("no exception text reaches a visitor", () => {
  it("visitorMessage shows the API's sentence and hides everything else", () => {
    expect(visitorMessage(new ApiError(429, "You've used today's 5 free drafts. Come back tomorrow."), DRAFT_FAILED))
      .toBe("You've used today's 5 free drafts. Come back tomorrow.");
    expect(visitorMessage(new ApiError(422, 'API 422: {"detail":[...]}'), DRAFT_FAILED)).toBe(DRAFT_FAILED);
    expect(visitorMessage(new TypeError("Failed to fetch"), DESK_FAILED)).toBe(DESK_FAILED);
    expect(visitorMessage(new Error("KeyError: 'strike'"), TRADES_FAILED)).toBe(TRADES_FAILED);
    expect(visitorMessage("boom", SAVE_FAILED)).toBe(SAVE_FAILED);
    for (const s of [DRAFT_FAILED, DESK_FAILED, TRADES_FAILED, ALTERNATIVE_FAILED, SAVE_FAILED]) {
      expect(s).toMatch(/\.$/);
      expect(s).not.toMatch(/error|exception|failed:|\{/i);
    }
  });

  it("Build, the desk and the trades page never render err.message", () => {
    for (const page of ["app/build/page.tsx", "app/ivy/desk/page.tsx", "app/ivy/trades/page.tsx"]) {
      const src = read(page);
      expect(src, page).not.toMatch(/err(or)?\.message/);
      expect(src, page).not.toMatch(/err instanceof Error \? err\.message/);
      expect(src, page).toContain("visitorMessage(");
    }
    const build = read("app/build/page.tsx");
    expect(build).toMatch(/setAltError\(visitorMessage\(err, ALTERNATIVE_FAILED\)\)/);   // a 429 shows the limit's own sentence
    expect(build).toContain("{altError}");
    expect(build).not.toContain("Couldn't generate an alternative");
  });
});
