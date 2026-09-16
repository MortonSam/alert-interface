"use client";

import posthog from "posthog-js";
import { PostHogProvider as PHProvider } from "posthog-js/react";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

export default function PostHogProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const initialized = useRef(false);

  useEffect(() => {
    const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
    const host = process.env.NEXT_PUBLIC_POSTHOG_HOST;
    if (!key || initialized.current) return;
    if (typeof window !== "undefined" && localStorage.getItem("admin_token")) return;

    posthog.init(key, {
      api_host: host || "https://us.i.posthog.com",
      capture_pageview: false,
      capture_pageleave: true,
      session_recording: { maskAllInputs: true },
      persistence: "localStorage+cookie",
    });
    initialized.current = true;
  }, []);

  useEffect(() => {
    if (initialized.current) {
      posthog.capture("$pageview");
    }
  }, [pathname]);

  return <PHProvider client={posthog}>{children}</PHProvider>;
}
