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
          {/* Build a Trade — primary CTA */}
          <Link
            href="/build"
            className="rounded-lg border-2 border-primary/40 bg-primary/5 p-6 block hover:bg-primary/10 hover:border-primary/60 transition-colors group"
          >
            <div className="flex items-center gap-2 mb-2">
              <h2 className="font-semibold group-hover:underline">Build a Trade</h2>
              <span className="text-[10px] bg-primary text-primary-foreground px-1.5 py-0.5 rounded font-bold uppercase tracking-wide">
                New
              </span>
            </div>
            <p className="text-sm text-muted-foreground">
              Pick a stock, choose a direction, and get an AI-drafted trade idea grounded
              in options data, earnings history, and volatility. Saves to your tracker.
            </p>
          </Link>

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
              Review and resolve your open theses. Track option P&amp;L mark-to-market,
              grade your calls, and record reflections.
            </p>
          </Link>
        </div>

        <TickerGrid />
      </div>
    </main>
  );
}
