import type { VerificationClaim, VerificationResult } from "@/lib/api";

/**
 * One final verdict per claim. The badge on a claim and the totals above the claims read the same field: the claim's verdict.
 * The API recounts the summary from the claims (backend services/verification_verdicts), and the page counts again here, so a
 * stored summary that disagrees with its claims can never reach the screen.
 */
export type Verdict = "supported" | "unsupported" | "contradicted";
export const VERDICTS: readonly Verdict[] = ["supported", "unsupported", "contradicted"];

export function claimVerdict(c: Pick<VerificationClaim, "verdict" | "status">): Verdict {
  const v = (c.verdict ?? c.status) as string;
  return (VERDICTS as readonly string[]).includes(v) ? (v as Verdict) : "unsupported";
}

export function claimReason(c: Pick<VerificationClaim, "reason" | "evidence">): string {
  return c.reason ?? c.evidence ?? "";
}

/** The totals, counted from the claims' verdicts. */
export function verdictTotals(claims: readonly Pick<VerificationClaim, "verdict" | "status">[]): Record<Verdict, number> {
  const out: Record<Verdict, number> = { supported: 0, unsupported: 0, contradicted: 0 };
  for (const c of claims) out[claimVerdict(c)] += 1;
  return out;
}

/** True when the stored summary equals the claims' count: a note that fails this is showing two different stories. */
export function verificationConsistent(v: Pick<VerificationResult, "claims" | "summary">): boolean {
  const t = verdictTotals(v.claims);
  return VERDICTS.every((k) => v.summary[k] === t[k]);
}
