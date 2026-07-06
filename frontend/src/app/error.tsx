"use client";

import { useEffect } from "react";
import Link from "next/link";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="min-h-[80vh] flex items-center justify-center p-8">
      <div className="text-center space-y-4">
        <p className="font-mono text-xs uppercase tracking-[.16em] text-muted-foreground">
          Something went wrong
        </p>
        <h1 className="font-display text-3xl font-bold text-foreground">
          That didn&apos;t load right.
        </h1>
        <p className="text-sm text-muted-foreground">
          An unexpected error occurred.
        </p>
        <div className="flex items-center justify-center gap-4 pt-4">
          <button
            onClick={reset}
            className="rounded-xl bg-primary text-primary-foreground px-6 py-3 text-sm font-semibold hover:opacity-90 transition-opacity"
          >
            Try again
          </button>
          <Link
            href="/"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            &larr; Back home
          </Link>
        </div>
      </div>
    </main>
  );
}
