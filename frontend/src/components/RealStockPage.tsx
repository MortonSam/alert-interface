import Link from "next/link";
import { Briefing } from "@/components/Briefing";
import { insightAsOfLine } from "@/lib/insightHeadline";
import type { FeaturedExample } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

/** The featured example, fetched on the server: the nightly rule's pick with its catalyst and pattern sentences;
 * null when no ticker qualifies or the API cannot be reached. */
async function featuredExample(): Promise<FeaturedExample | null> {
  try {
    const res = await fetch(`${API}/v1/discover/featured`, { cache: "no-store" });
    if (!res.ok) return null;
    const body = (await res.json()) as FeaturedExample;
    return body.symbol && body.sentences?.length ? body : null;
  } catch {
    return null;
  }
}

/** One compact block from a real stock page: the ticker the nightly rule chose, rendered through the same Briefing
 * component the ticker page uses, with the night it was chosen. Renders nothing when no ticker qualifies. */
export default async function RealStockPage() {
  const view = await featuredExample();
  if (!view) return null;
  const picked = insightAsOfLine(view.picked_on);
  return (
    <div className="max-w-3xl w-full mx-auto">
      <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-6 text-center">From a real stock page</p>
      <div className="border border-border rounded-2xl px-6 py-7 sm:px-10 sm:py-9">
        <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground mb-4">{view.name ?? view.symbol} · {view.symbol} · Overview</p>
        <Briefing sentences={view.sentences} />
        <div className="mt-6 flex flex-wrap items-baseline gap-x-6 gap-y-2">
          <Link href={`/tickers/${view.symbol}`} className="inline-block text-sm font-semibold text-primary hover:opacity-80 transition-opacity">
            See {view.name ?? view.symbol}&apos;s full page →
          </Link>
          {view.rule && picked && (
            <p className="text-[11px] text-muted-foreground/70">Chosen nightly by rule ({view.rule}); {picked.replace("As of", "picked")}.</p>
          )}
        </div>
      </div>
    </div>
  );
}
