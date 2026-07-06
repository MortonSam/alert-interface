import Link from "next/link";

export default function NotFound() {
  return (
    <main className="min-h-[80vh] flex items-center justify-center p-8">
      <div className="text-center space-y-4">
        <p className="font-mono text-xs uppercase tracking-[.16em] text-muted-foreground">
          404
        </p>
        <h1 className="font-display text-3xl font-bold text-foreground">
          This page doesn&apos;t exist.
        </h1>
        <p className="text-sm text-muted-foreground">
          The page you&apos;re looking for isn&apos;t here.
        </p>
        <div className="flex items-center justify-center gap-4 pt-4">
          <Link
            href="/"
            className="rounded-xl bg-primary text-primary-foreground px-6 py-3 text-sm font-semibold hover:opacity-90 transition-opacity"
          >
            &larr; Back home
          </Link>
          <Link
            href="/discover"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Discover &rarr;
          </Link>
        </div>
      </div>
    </main>
  );
}
