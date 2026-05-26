import { TickerGrid } from "./ticker-grid";

export default function Home() {
  return (
    <main className="min-h-screen p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight">Alert Interface</h1>
          <p className="text-muted-foreground mt-1">Personal finance research tool</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="rounded-lg border bg-card p-6">
            <h2 className="font-semibold mb-2">Catalyst Panel</h2>
            <p className="text-sm text-muted-foreground">
              Upcoming events in the next 60 days — earnings, macro releases, FDA dates,
              ex-div, product launches. Historical reactions table per ticker.
            </p>
          </div>

          <div className="rounded-lg border bg-card p-6">
            <h2 className="font-semibold mb-2">Watchlists</h2>
            <p className="text-sm text-muted-foreground">
              Track your positions and monitor catalysts across your portfolio.
              Push notifications via ntfy.sh.
            </p>
          </div>

          <div className="rounded-lg border bg-card p-6">
            <h2 className="font-semibold mb-2">AI Research</h2>
            <p className="text-sm text-muted-foreground">
              Claude-powered one-pagers and thesis tracking. New filings are graded
              against your prior view automatically.
            </p>
          </div>
        </div>

        <TickerGrid />
      </div>
    </main>
  );
}
