import Link from "next/link";
import { InsightHeadline } from "@/components/InsightHeadline";
import { hasInsight, type InsightView } from "@/lib/insightHeadline";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";
export const REAL_PAGE_SYMBOL = "MU";
export const REAL_PAGE_NAME = "Micron";

/** The stored insight for the real page, fetched on the server; null when the API has none or cannot be reached. */
async function realPageInsight(): Promise<InsightView | null> {
  try {
    const res = await fetch(`${API}/v1/discover/insight/${REAL_PAGE_SYMBOL}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as InsightView;
  } catch {
    return null;
  }
}

/** One compact block from a real stock page: the same headline component and the same stored stat the ticker page
 * shows, fetched server-side. Renders nothing when the stat is absent. */
export default async function RealStockPage() {
  const view = await realPageInsight();
  if (!hasInsight(view)) return null;
  return (
    <div className="max-w-3xl w-full mx-auto">
      <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-6 text-center">From a real stock page</p>
      <div className="border border-border rounded-2xl px-6 py-7 sm:px-10 sm:py-9">
        <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground mb-4">{REAL_PAGE_NAME} · {REAL_PAGE_SYMBOL} · Overview</p>
        <InsightHeadline insight={view.insight} rule={view.rule} asOf={view.as_of} />
        <Link href={`/tickers/${REAL_PAGE_SYMBOL}`} className="inline-block mt-6 text-sm font-semibold text-primary hover:opacity-80 transition-opacity">
          See {REAL_PAGE_NAME}&apos;s full page →
        </Link>
      </div>
    </div>
  );
}
