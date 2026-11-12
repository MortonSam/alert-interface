"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { capture, setAnalyticsClient } from "@/lib/analytics";
import { CONSENT_KEY, analyticsAllowed, readConsent } from "@/lib/consent";

/** PostHog starts only after the visitor accepts analytics (lib/consent); until then nothing is captured, no session is recorded
 *  and posthog-js itself is not downloaded (it is imported here, after the consent check, never at the top of a file).
 *  A browser holding the admin token is never recorded. The consent banner (a separate component) writes the choice and dispatches
 *  a "consent-changed" event so a visitor who accepts mid-visit is recorded from then on. */
export default function PostHogProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const initialized = useRef(false);
  const starting = useRef(false);
  const [consent, setConsent] = useState(() => readConsent());

  useEffect(() => {
    const onChange = () => setConsent(readConsent());
    window.addEventListener("consent-changed", onChange);
    window.addEventListener("storage", (e) => { if (e.key === CONSENT_KEY) onChange(); });
    return () => window.removeEventListener("consent-changed", onChange);
  }, []);

  useEffect(() => {
    const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
    const host = process.env.NEXT_PUBLIC_POSTHOG_HOST;
    if (!key || initialized.current || starting.current || !analyticsAllowed(consent)) return;
    if (typeof window !== "undefined" && localStorage.getItem("admin_token")) return;

    starting.current = true;
    import("posthog-js").then(({ default: posthog }) => {
      if (!analyticsAllowed(readConsent())) return;   // withdrawn while the file was on its way
      posthog.init(key, {
        api_host: host || "https://us.i.posthog.com",
        capture_pageview: false,
        capture_pageleave: true,
        session_recording: { maskAllInputs: true },
        persistence: "localStorage+cookie",
      });
      initialized.current = true;
      setAnalyticsClient(posthog);
      posthog.capture("$pageview");
    }).catch(() => { /* analytics never breaks the page */ }).finally(() => { starting.current = false; });
  }, [consent]);

  useEffect(() => {
    if (initialized.current) {
      capture("$pageview");
    }
  }, [pathname]);

  return <>{children}</>;
}
