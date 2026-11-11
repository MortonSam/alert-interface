import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { ACCOUNT_COPY } from "@/lib/accountCopy";
import { PRIVACY_DRAFT, TERMS_DRAFT } from "@/lib/legalDrafts";

// Sam's rules for accounts (2026-10-29): nothing grabby (no pop-ups, countdowns, "last chance" or walls), no buy or sell words, every
// email opt-in, and the only prompts sit where an unlocked feature is.
const ADVICE = /\b(?:buy|sell|should|consider|opportunit\w*|act now|don't miss)\b/i;
const URGENCY = /\b(?:now|hurry|last chance|limited time|only \d+ left|expires? soon|countdown)\b|!/i;
const strings = (o: unknown): string[] => (typeof o === "string" ? [o] : typeof o === "function" ? [String((o as (x: string) => string)("NVIDIA"))]
  : o && typeof o === "object" ? Object.values(o).flatMap(strings) : []);

describe("the account screens' words", () => {
  it("never press and never say buy or sell", () => {
    const bad = strings(ACCOUNT_COPY).filter((s) => ADVICE.test(s) || URGENCY.test(s));
    expect(bad).toEqual([]);
  });
  it("the legal drafts are marked as drafts and press nothing", () => {
    for (const doc of [PRIVACY_DRAFT, TERMS_DRAFT]) {
      expect(doc.status).toBe("Draft for review, not in force");
      expect(doc.sections.flatMap((s) => s.paragraphs).filter((p) => URGENCY.test(p))).toEqual([]);
    }
    expect(PRIVACY_DRAFT.sections.map((s) => s.heading)).toContain("Deleting your data");
  });
  it("with accounts off the new routes are the not-found page, never a blank one (Sam, 2026-11-10)", () => {
    const SRC = join(__dirname, "..", "..");
    const read = (f: string) => readFileSync(join(SRC, f), "utf8");
    // /account and /account/verify through one layout, the results through theirs, /privacy and /terms through the page they share
    for (const f of ["app/account/layout.tsx", "app/alerts-trades/results/layout.tsx", "components/legal/LegalPage.tsx"]) {
      expect(read(f), f).toContain("if (!ACCOUNTS_ON) notFound();");
      expect(read(f), f).not.toContain('"use client"');
    }
    for (const f of ["app/privacy/page.tsx", "app/terms/page.tsx"]) expect(read(f), f).toContain("<LegalPage doc=");
    for (const f of ["app/account/page.tsx", "app/account/verify/page.tsx", "app/alerts-trades/results/page.tsx", "components/legal/LegalPage.tsx"]) {
      expect(read(f), f).not.toMatch(/if \(!ACCOUNTS_ON\) return </);
    }
  });
  it("the prompts appear only at Ask Ivy's box, the follow star, Build a Trade's save and the ticker page's email line", () => {
    const SRC = join(__dirname, "..", "..");
    const uses = ["components/AskIvy.tsx", "app/build/page.tsx", "app/tickers/[symbol]/page.tsx", "components/AccountFollow.tsx", "app/alerts-trades/results/page.tsx"]
      .filter((f) => /AccountPrompt|LocalFollow|EarningsEmailLine|SAVE_REQUIRES_SIGN_IN/.test(readFileSync(join(SRC, f), "utf8")));
    expect(uses.length).toBe(5);
    const layout = readFileSync(join(SRC, "app/layout.tsx"), "utf8");
    expect(layout).not.toMatch(/AccountPrompt|LocalFollow|modal|dialog/i);                // nothing site-wide, no pop-up
  });
});
