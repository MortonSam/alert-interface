// TODO: Remove this page after verifying Sentry captures errors end-to-end.
"use client";

import { useEffect } from "react";

export default function SentryTestPage() {
  useEffect(() => {
    throw new Error("Sentry frontend test — delete this page after verifying capture");
  }, []);

  return null;
}
