import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import {
  IVY_OUTCOME_LABELS, PRIVATE_LEDGER_BODY, impliedMoveAbsentLabel, ivyOutcomeLabel, nightSummary,
} from "../ivyOutcomes";

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
    expect(nightSummary({ evaluated: 41, picked: 1, refused: 6, passed: 33, errors: 1 }))
      .toBe("evaluated 41 names: picked 1, refused 6, passed on 33, 1 error");
    expect(nightSummary({ evaluated: 1, picked: 0, refused: 0, passed: 1, errors: 0 }))
      .toBe("evaluated 1 name: picked 0, refused 0, passed on 1");
  });

  it("no chain and unpriceable options are different labels", () => {
    expect(impliedMoveAbsentLabel("no_fresh_chain")).toBe("no current options data");
    expect(impliedMoveAbsentLabel("vol_gate")).toBe("options could not be priced");
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
