import type { PostHog } from "posthog-js";

// posthog-js is downloaded only after the visitor accepts analytics (components/PostHogProvider), so a visitor who has not
// accepted never fetches it. Until it has started, every capture is dropped.
let client: PostHog | null = null;

/** The started PostHog client, handed over by PostHogProvider once the visitor has accepted. */
export function setAnalyticsClient(started: PostHog): void {
  client = started;
}

export function capture(event: string, properties?: Record<string, string | number | boolean>) {
  if (typeof window !== "undefined" && client?.__loaded) {
    client.capture(event, properties);
  }
}
