// Analytics consent: PostHog (page views and session replay) runs only after the visitor accepts. The choice is kept in this
// browser's localStorage; nothing is recorded before it, and a decline is remembered the same way. The banner that asks lives
// beside this file; its words are held for Sam's approval.
export const CONSENT_KEY = "analytics_consent";
export type Consent = "accepted" | "declined" | null;

export function readConsent(storage: Pick<Storage, "getItem"> | null = typeof window === "undefined" ? null : window.localStorage): Consent {
  try {
    const v = storage?.getItem(CONSENT_KEY);
    return v === "accepted" || v === "declined" ? v : null;
  } catch {
    return null;
  }
}

export function writeConsent(choice: Exclude<Consent, null>, storage: Pick<Storage, "setItem"> | null = typeof window === "undefined" ? null : window.localStorage): void {
  try { storage?.setItem(CONSENT_KEY, choice); } catch { /* a blocked store means no analytics, which is the safe side */ }
}

/** Analytics may start only on an explicit "accepted". */
export function analyticsAllowed(consent: Consent): boolean {
  return consent === "accepted";
}
