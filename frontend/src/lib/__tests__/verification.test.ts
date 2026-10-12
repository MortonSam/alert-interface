import { describe, expect, it } from "vitest";
import type { VerificationClaim } from "@/lib/api";
import { claimReason, claimVerdict, verdictTotals, verificationConsistent } from "@/lib/verification";

const claim = (verdict: VerificationClaim["verdict"], reason = "the filing says so"): VerificationClaim =>
  ({ claim: "x", verdict, reason, status: verdict, evidence: reason });

describe("one verdict per claim", () => {
  it("counts the totals from the claims, never from a stored summary", () => {
    const claims = [claim("supported"), claim("supported"), claim("unsupported"), claim("contradicted")];
    expect(verdictTotals(claims)).toEqual({ supported: 2, unsupported: 1, contradicted: 1 });
  });

  it("fails a note whose badges and totals disagree", () => {
    const claims = [claim("supported"), claim("unsupported")];
    expect(verificationConsistent({ claims, summary: { supported: 1, unsupported: 1, contradicted: 0 } })).toBe(true);
    expect(verificationConsistent({ claims, summary: { supported: 22, unsupported: 9, contradicted: 0 } })).toBe(false);   // AAPL's stored note on 2026-10-12
  });

  it("reads an older claim's status and evidence as its verdict and reason, and an unknown verdict as unsupported", () => {
    const old = { claim: "y", status: "contradicted", evidence: "the stats say 12" } as unknown as VerificationClaim;
    expect(claimVerdict(old)).toBe("contradicted");
    expect(claimReason(old)).toBe("the stats say 12");
    expect(claimVerdict({ status: "maybe" } as unknown as VerificationClaim)).toBe("unsupported");
  });
});
