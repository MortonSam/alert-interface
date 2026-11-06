"use client";

// The ticker page's two account touches (Sam, 2026-10-29), only while NEXT_PUBLIC_ACCOUNTS_ENABLED is "true": the follow star for a
// visitor (kept in this browser until they sign in, then moved into the account) and one quiet line offering the earnings-eve email.
import { useEffect, useState } from "react";
import Link from "next/link";
import { ACCOUNTS_ON, account, readLocalWatchlist, writeLocalWatchlist } from "@/lib/account";
import { ACCOUNT_COPY as C } from "@/lib/accountCopy";

export function LocalFollow({ symbol }: { symbol: string }) {
  const [following, setFollowing] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => { setFollowing(readLocalWatchlist().includes(symbol)); }, [symbol]);
  if (!ACCOUNTS_ON) return null;
  return (
    <span className="inline-flex flex-col gap-1">
      <button type="button" aria-pressed={following} className="tap rounded-xl border border-border px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground"
        onClick={() => {
          const list = readLocalWatchlist();
          const next = following ? list.filter((s) => s !== symbol) : [...list, symbol];
          writeLocalWatchlist(next);
          setFollowing(!following);
          setSaved(!following);
        }}>
        {following ? `★ ${C.starFollowing}` : `☆ ${C.starAdd}`}
      </button>
      {saved && <span className="text-xs text-muted-foreground">{C.starPrompt} <Link href="/account" className="text-primary">{C.signInLink} →</Link></span>}
    </span>
  );
}

export function EarningsEmailLine({ symbol, name }: { symbol: string; name: string }) {
  const [shown, setShown] = useState(false);
  useEffect(() => { if (ACCOUNTS_ON) setShown(true); }, []);
  if (!shown) return null;
  return (
    <p className="mt-2 text-sm" data-testid="earnings-email-line">
      <Link href={`/account?follow=${encodeURIComponent(symbol)}&name=${encodeURIComponent(name)}`} className="text-muted-foreground hover:text-foreground">
        {C.tickerEmailLine(name)} →
      </Link>
    </p>
  );
}

/** Whether this browser is signed in to an email account (null while unknown). */
export function useAccountSignedIn(): boolean | null {
  const [v, setV] = useState<boolean | null>(null);
  useEffect(() => { if (ACCOUNTS_ON) account.me().then((r) => setV(r.ok)); else setV(false); }, []);
  return v;
}
