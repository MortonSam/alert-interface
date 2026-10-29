"use client";

// Hypothetical results (Sam, 2026-10-29): every saved trade idea with an option leg, scored after its expiration from stored prices
// (backend services/trade_results), with the running summary. Labeled "Hypothetical"; no money, no buy or sell language.
import { useEffect, useState } from "react";
import AccountPrompt from "@/components/AccountPrompt";
import { ACCOUNTS_ON, account, type ResultItem } from "@/lib/account";
import { ACCOUNT_COPY as C } from "@/lib/accountCopy";
import { fmtDate } from "@/lib/dates";

const usd = (x: number) => `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signedPct = (x: number | null) => (x == null ? C.notOnFile : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(1)}%`);

function label(i: ResultItem): string {
  const strikes = `$${i.strike ?? ""}${i.strike2 != null ? `/$${i.strike2}` : ""}`;
  return `${i.symbol} ${i.expiration ? fmtDate(i.expiration) : ""} ${strikes} ${i.option_type}${i.strike2 != null ? " spread" : ""}`;
}

export default function ResultsPage() {
  const [data, setData] = useState<{ summary: string | null; items: ResultItem[] } | null | undefined>(undefined);
  useEffect(() => { if (ACCOUNTS_ON) account.results().then((r) => setData(r.ok ? r.data : null)); }, []);
  if (!ACCOUNTS_ON) return <main className="max-w-7xl mx-auto px-4 sm:px-8 py-10" />;
  return (
    <main className="max-w-3xl mx-auto px-4 sm:px-8 py-10">
      <p className="font-mono text-xs uppercase tracking-[.16em] text-primary">{C.hypothetical}</p>
      <h1 className="mt-2 text-display font-display font-bold text-foreground">{C.resultsTitle}</h1>
      <p className="mt-3 text-foreground/85">{C.resultsBody}</p>
      {data === null && <div className="mt-6"><AccountPrompt text={C.savePrompt} /></div>}
      {data && (
        <>
          {data.summary && <p className="mt-6 font-semibold">{data.summary}</p>}
          {data.items.length === 0 && <p className="mt-6 text-muted-foreground">{C.resultsEmpty}</p>}
          <ul className="mt-4 divide-y divide-border/60">
            {data.items.map((i) => (
              <li key={i.id} className="py-4">
                <p className="text-sm font-medium">{label(i)} <span className="ml-2 rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">{C.hypothetical}</span></p>
                {i.result ? (
                  <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                    <dt className="text-muted-foreground">{C.costLabel}</dt><dd>{usd(i.result.paid_usd)}</dd>
                    <dt className="text-muted-foreground">{C.worthLabel}</dt><dd>{usd(i.result.worth_usd)}</dd>
                    <dt className="text-muted-foreground">{C.resultLabel}</dt><dd>{usd(i.result.result_usd)} ({signedPct(i.result.result_pct)})</dd>
                    <dt className="text-muted-foreground">{C.moveLabel}</dt><dd>{signedPct(i.result.stock_move_pct)}</dd>
                    <dt className="text-muted-foreground">{C.pricedLabel}</dt>
                    <dd>{i.result.priced_move_pct != null ? `±${i.result.priced_move_pct.toFixed(1)}%${i.result.moved_vs_priced ? `, it moved ${C.movedVsPriced[i.result.moved_vs_priced]}` : ""}` : C.notOnFile}</dd>
                  </dl>
                ) : <p className="mt-1 text-sm text-muted-foreground">{C.waiting}</p>}
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  );
}
