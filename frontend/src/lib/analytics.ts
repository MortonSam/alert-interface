import posthog from "posthog-js";

export function capture(event: string, properties?: Record<string, string>) {
  if (typeof window !== "undefined" && posthog.__loaded) {
    posthog.capture(event, properties);
  }
}
