import { TickerGrid } from "./ticker-grid";

export default function Home() {
  return (
    <main className="min-h-screen p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight">Alert Interface</h1>
          <p className="text-muted-foreground mt-1">Research any stock, then build a trade with confidence.</p>
        </div>

        <TickerGrid />
      </div>
    </main>
  );
}
