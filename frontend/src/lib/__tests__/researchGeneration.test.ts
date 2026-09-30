import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "../..");
const page = readFileSync(join(SRC, "app/tickers/[symbol]/page.tsx"), "utf8");

describe("Research section: generation rules come from the API", () => {
  it("shows the button when the policy allows it, the owner-only sentence when it does not, never a localStorage check", () => {
    expect(page).toMatch(/genPolicy\.can_generate && \([\s\S]{0,400}handleGenerate\(\)/);
    expect(page).toMatch(/!genPolicy\.can_generate && genPolicy\.owner_only_message/);
    expect(page).not.toContain('localStorage.getItem("admin_token")');
  });
  it("the limits and the expected wait are rendered from the policy, not retyped", () => {
    expect(page).toContain("genPolicy.per_ip_hour} per hour and {genPolicy.per_ip_day} per day per visitor");
    expect(page).toMatch(/genPolicy\.expected_wait_seconds\[0\]\} to \{genPolicy\.expected_wait_seconds\[1\]\} seconds/);
    expect(page).not.toMatch(/~40 seconds|30 to 60 seconds|5 per hour/);
  });
  it("a 429 or 403 shows the API's sentence and does not mark the note failed", () => {
    expect(page).toMatch(/e\.status === 429 \|\| e\.status === 403 \|\| e\.status === 409\)\) \{\s*setGenerateRefusal\(e\.message\);[^\n]*\n\s*return;/);
    expect(page).toMatch(/\{generateRefusal && \(\s*<Callout severity="caution">\{generateRefusal\}<\/Callout>/);
  });
  it("only the owner's regenerate passes force, and only the owner sees a Regenerate or Try Again (audit item 13)", () => {
    expect(page).toMatch(/function handleRegenerate\(\) \{[\s\S]{0,200}handleGenerate\(\{ force: true \}\)/);
    expect(page.match(/genPolicy\?\.can_regenerate && \(\s*<button\s+onClick=\{handleRegenerate\}/g)?.length).toBe(2);
    // a failed generation produced no note, so Try Again is a first generation: gated like one, never with force
    expect(page).toMatch(/genPolicy\?\.can_generate \? \(\s*<button\s+onClick=\{\(\) => void handleGenerate\(\)\}[\s\S]{0,300}Try Again/);
    expect(page).toContain("?? OWNER_REGENERATES}");
    expect(page.match(/onClick=\{handleRegenerate\}/g)?.length).toBe(2);
    // the first note for a ticker that has none is still the visitor's to ask for
    expect(page).toMatch(/noteStatus === "empty" && \([\s\S]{0,300}genPolicy\.can_generate && \(/);
  });
});
