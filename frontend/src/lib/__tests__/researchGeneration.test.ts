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
    expect(page).toMatch(/e\.status === 429 \|\| e\.status === 403 \|\| e\.status === 409\)\) \{\s*setGenerateRefusal\(visitorMessage\(e\)\);[^\n]*\n\s*return;/);
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

describe("no raw error reaches a visitor (Sam, 2026-10-27)", () => {
  it("every failure the page shows goes through visitorMessage, and an API body that is not a sentence never shows", async () => {
    const { readFileSync, readdirSync, statSync } = await import("node:fs");
    const { join } = await import("node:path");
    const root = join(__dirname, "..", "..");
    const files: string[] = [];
    const walk = (d: string) => { for (const f of readdirSync(d)) { const p = join(d, f); if (statSync(p).isDirectory()) { if (f !== "__tests__") walk(p); } else if (/\.tsx?$/.test(f)) files.push(p); } };
    walk(root);
    const raw = files.filter((p) => /set\w*(Error|Refusal)\(\s*(e|err|error)\.message\b|error:\s*(e|err)\s*instanceof Error \? (e|err)\.message/.test(readFileSync(p, "utf8")));
    expect(raw).toEqual([]);
    const { errorMessage, UNEXPECTED_MESSAGE } = await import("@/lib/api");
    expect(await errorMessage(new Response("<html>502 Bad Gateway</html>", { status: 502 }))).toBe(UNEXPECTED_MESSAGE);
    expect(await errorMessage(new Response(JSON.stringify({ detail: [{ loc: ["body"], msg: "x" }] }), { status: 422 }))).toBe(UNEXPECTED_MESSAGE);
    expect(await errorMessage(new Response(JSON.stringify({ detail: "Ivy couldn't write this note right now. Try again in a few minutes." }), { status: 502 })))
      .toBe("Ivy couldn't write this note right now. Try again in a few minutes.");
  });
});
