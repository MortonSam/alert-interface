"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchFeatured, HOME_ENTRY, type Featured } from "@/lib/walkthrough";

/** The home page's entry: opens the walkthrough of the stock chosen nightly by the featured rule (backend
 *  services/walkthrough_compare.FEATURED_RULE). Hidden when no stock qualifies. */
export default function LearnEntry({ className }: { className: string }) {
  const [f, setF] = useState<Featured | null>(null);
  useEffect(() => { fetchFeatured().then(setF); }, []);
  if (!f?.symbol || !f.minutes) return null;
  return (
    <Link href={`/tickers/${f.symbol}?learn=1`} className={className}>
      {HOME_ENTRY(f.minutes)}
    </Link>
  );
}
