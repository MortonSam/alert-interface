"use client";

import posthog from "posthog-js";
import { PostHogProvider as PHProvider } from "posthog-js/react";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { CONSENT_KEY, analyticsAllowed, readConsent } from "@/lib/consent";

/** PostHog starts only after the visitor accepts analytics (lib/consent); until then nothing is captured and no session is recorded.
 *  A browser holding the admin token is never recorded. The consent banner (a separate component) writes the choice and dispatches
 *  a "consent-changed" event so a visitor who accepts mid-visit is recorded from then on. */
export default function PostHogProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const initialized = useRef(false);
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
    if (!key || initialized.current || !analyticsAllowed(consent)) return;
    if (typeof window !== "undefined" && localStorage.getItem("admin_token")) return;

    posthog.init(key, {
      api_host: host || "https://us.i.posthog.com",
      capture_pageview: false,
      capture_pageleave: true,
      session_recording: { maskAllInputs: true },
      persistence: "localStorage+cookie",
    });
    initialized.current = true;
    posthog.capture("$pageview");
  }, [consent]);

  useEffect(() => {
    if (initialized.current) {
      posthog.capture("$pageview");
    }
  }, [pathname]);

  return <PHProvider client={posthog}>{children}</PHProvider>;
}
