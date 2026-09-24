import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import {
  IVY_OUTCOME_LABELS, NIGHT_SUMMARY_KEY, PRIVATE_LEDGER_BODY, impliedMoveAbsentLabel, ivyOutcomeLabel, nightSummary,
} from "../ivyOutcomes";
import { runFailureLine } from "../ivyOutcomes";

const SRC = join(__dirname, "../..");
const backend = (p: string) => readFileSync(join(SRC, "../../backend/app", p), "utf8");

describe("Ivy's desk outcomes", () => {
  it("labels every outcome the backend can record, and nothing else", () => {
    const map = backend("services/ivy_outcomes.py");
    const block = map.slice(map.indexOf("IVY_OUTCOMES"), map.indexOf("\n}\n", map.indexOf("IVY_OUTCOMES")));
    const backendKeys = [...block.matchAll(/^\s+"([a-z_]+)":\s+\{/gm)].map((m) => m[1]);
    expect(backendKeys.length).toBeGreaterThanOrEqual(11);
    expect(Object.keys(IVY_OUTCOME_LABELS).sort()).toEqual([...backendKeys].sort());
  });

  it("the backend map covers every outcome its own code writes", () => {
    const written = new Set<string>();
    for (const file of ["scripts/auto_pick.py", "routers/thesis.py"]) {
      for (const m of backend(file).matchAll(/outcome\s*==?\s*"([a-z_]+)"/g)) written.add(m[1]);
    }
    for (const o of written) expect(Object.keys(IVY_OUTCOME_LABELS), `backend writes "${o}"`).toContain(o);
  });

  it("labels match the backend's wording", () => {
    const map = backend("services/ivy_outcomes.py");
    for (const [key, label] of Object.entries(IVY_OUTCOME_LABELS)) expect(map, key).toContain(`"label": "${label}"`);
  });

  it("an unknown outcome never shows a raw code", () => {
    expect(ivyOutcomeLabel("some_new_code")).toBe("Outcome not recognised");
  });

  it("the night's sentence separates picked, refused, passed and errors", () => {
    expect(nightSummary({ evaluated: 41, picked: 1, refused: 6, passed: 32, holding: 1, errors: 1 }))
      .toBe("evaluated 41 names: picked 1, refused 6, passed 32, holding 1, 1 error");
    expect(nightSummary({ evaluated: 1, picked: 0, refused: 0, passed: 1, errors: 0 }))
      .toBe("evaluated 1 name: picked 0, refused 0, passed 1, holding 0");
  });

  it("no chain and unpriceable options are different labels", () => {
    expect(impliedMoveAbsentLabel("no_fresh_chain")).toBe("not priced: no current options data");
    // without a stored reason the cell never claims a pricing failure the evaluation did not have
    expect(impliedMoveAbsentLabel("vol_gate")).toBe("not priced: reason not recorded");
    expect(readFileSync(join(SRC, "app/ivy/desk/page.tsx"), "utf8")).not.toContain(">no chain<");
  });

  it("the desk and the trades page tell an anonymous visitor the same thing", () => {
    for (const p of ["app/ivy/desk/page.tsx", "app/ivy/trades/page.tsx"]) {
      const src = readFileSync(join(SRC, p), "utf8");
      expect(src, p).toContain("PRIVATE_LEDGER_BODY");
      expect(src, p).toContain("nightSummary(activity)");
      expect(src, p).not.toMatch(/passed on \{/);
    }
    expect(PRIVATE_LEDGER_BODY).toContain("go public at launch");
    const desk = readFileSync(join(SRC, "app/ivy/desk/page.tsx"), "utf8");
    expect(desk).not.toContain("depends on market hours");
    expect(desk).toContain("chainFreshnessSentence(");
  });
});

describe("the desk says when the nightly did not complete", () => {
  it("failed run with a worksheet to fall back on", () => {
    expect(runFailureLine({ last_run_at: "2026-09-23T06:16:18+00:00", last_run_exit: 1, last_run_error: "X: invalid input syntax for type json", last_run_stale: false, last_run_failed: true }, "Sep 22"))
      .toBe("Last night's evaluation did not complete (exit 1 at 06:16Z): X: invalid input syntax for type json. Showing the Sep 22 worksheet.");
  });
  it("killed at the timeout, no error text, no worksheet yet", () => {
    expect(runFailureLine({ last_run_at: "2026-09-23T06:26:18+00:00", last_run_exit: -1, last_run_error: null, last_run_stale: false, last_run_failed: true }, null))
      .toBe("Last night's evaluation did not complete (exit -1 at 06:26Z). No worksheet to show yet.");
  });
  it("a clean run that is older than the latest expected run", () => {
    expect(runFailureLine({ last_run_at: "2026-09-22T06:16:18+00:00", last_run_exit: 0, last_run_error: null, last_run_stale: true, last_run_failed: true }, "Sep 22"))
      .toBe("Ivy's nightly evaluation did not run last night (last completed at 06:16Z on 2026-09-22). Showing the Sep 22 worksheet.");
  });
  it("never recorded, and a clean current run", () => {
    expect(runFailureLine({ last_run_at: null, last_run_exit: null, last_run_error: null, last_run_stale: true, last_run_failed: true }, null))
      .toBe("Ivy's nightly evaluation has not run yet. No worksheet to show yet.");
    expect(runFailureLine({ last_run_at: "2026-09-23T06:16:18+00:00", last_run_exit: 0, last_run_failed: false }, "Sep 23")).toBeNull();
  });
});

describe("holding and the implied cell", () => {
  it("holding is a third verdict with its own definition in the legend", () => {
    expect(ivyOutcomeLabel("open_pick_exists")).toBe("Holding: already has an open pick in this name");
    expect(NIGHT_SUMMARY_KEY).toContain("Holding means she already has an open pick on the name and does not double up.");
  });
  it("the implied cell states the stored reason and never a pricing failure it did not have", () => {
    expect(impliedMoveAbsentLabel("open_pick_exists", "not priced: no current options data")).toBe("not priced: no current options data");
    expect(impliedMoveAbsentLabel("vol_gate", "options could not be priced: no usable ATM straddle in the chain")).toContain("could not be priced");
    expect(impliedMoveAbsentLabel("no_fresh_chain", null)).toBe("not priced: no current options data");
    expect(impliedMoveAbsentLabel("momentum_gate", undefined)).toBe("not priced: reason not recorded");
  });
});
