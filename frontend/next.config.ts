import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  // Proxy /api/* to FastAPI backend in dev — avoids CORS friction
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"}/:path*`,
      },
    ];
  },
};

// Sentry here reports errors only (instrumentation-client.ts: tracesSampleRate 0, no replay), so its tracing, replay and debug code
// is left out of the file every page downloads.
export default withSentryConfig(nextConfig, {
  silent: true,
  bundleSizeOptimizations: { excludeDebugStatements: true, excludeTracing: true, excludeReplayIframe: true, excludeReplayShadowDom: true, excludeReplayWorker: true },
});
