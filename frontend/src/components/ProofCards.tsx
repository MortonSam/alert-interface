"use client";

// Three live proof cards under the home hero (lib/proofCards). A card whose data is missing is left out; with none, the row is too.
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { earningsCard, ivyCard, unusualCard, type ProofCard } from "@/lib/proofCards";
import { moveTone } from "@/lib/newsSections";

const TONE: Record<ProofCard["tone"], string> = {
  accent: "text-primary", up: moveTone(1), down: moveTone(-1), plain: "text-foreground",
};

export function ProofCards() {
  const [cards, setCards] = useState<ProofCard[] | null>(null);
  useEffect(() => {
    let alive = true;
    (async () => {
      const [soon, active, activity] = await Promise.allSettled([
        api.discover.reportingSoon(7, 12), api.discover.unusuallyActive(12), api.theses.ivyActivity(),
      ]);
      const items = soon.status === "fulfilled" ? soon.value.items : null;
      const first = items?.find((i) => i.implied_move_pct != null && i.chain_date);
      const em = first ? await api.tickers.expectedMove(first.symbol).catch(() => null) : null;
      const out = [earningsCard(items, em), activity.status === "fulfilled" ? ivyCard(activity.value) : null,
                   unusualCard(active.status === "fulfilled" ? active.value.items : null)].filter((c): c is ProofCard => c != null);
      if (alive) setCards(out);
    })();
    return () => { alive = false; };
  }, []);

  if (cards === null) {
    return <div className="grid sm:grid-cols-3 border-t border-border" aria-hidden="true">{[0, 1, 2].map((i) => <div key={i} className="h-36 sm:border-l first:border-l-0 border-border" />)}</div>;
  }
  if (!cards.length) return null;
  return (
    <ul className={`grid border-t border-border ${cards.length === 3 ? "sm:grid-cols-3" : cards.length === 2 ? "sm:grid-cols-2" : ""}`} data-testid="proof-cards">
      {cards.map((c) => (
        <li key={c.key} className="border-b sm:border-b-0 sm:border-l first:sm:border-l-0 border-border">
          <Link href={c.href} className="group block h-full px-1 sm:px-6 first:sm:pl-0 py-5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
            <p className="text-xs text-muted-foreground">{c.kicker}</p>
            <p className="mt-1 text-sm font-semibold text-foreground group-hover:text-primary transition-colors">{c.title}</p>
            <p className={`mt-2 font-display text-3xl font-bold leading-none tabular-nums ${TONE[c.tone]}`}>{c.value}</p>
            {c.lines.map((l) => <p key={l} className="mt-2 text-xs text-foreground/70 leading-snug">{l}</p>)}
            <p className="mt-3 text-[11px] text-muted-foreground/70">{c.asOf}</p>
          </Link>
        </li>
      ))}
    </ul>
  );
}
