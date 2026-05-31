import Link from "next/link";
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

          <Link href="/watchlist" className="rounded-lg border bg-card p-6 block hover:bg-accent transition-colors group">
            <h2 className="font-semibold mb-2 group-hover:underline">Watchlists</h2>
            <p className="text-sm text-muted-foreground">
              Track your positions and monitor catalysts across your portfolio.
              Live prices, implied moves, and RV rank per row.
            </p>
          </Link>

          <Link href="/theses" className="rounded-lg border bg-card p-6 block hover:bg-accent transition-colors group">
            <h2 className="font-semibold mb-2 group-hover:underline">Thesis Tracker</h2>
            <p className="text-sm text-muted-foreground">
              Record and resolve directional bets. Track entry price, conviction,
              target date, and grade your own calls after the fact.
            </p>
          </Link>
        </div>

        <TickerGrid />
      </div>
    </main>
  );
}
