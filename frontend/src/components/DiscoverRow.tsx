import Link from "next/link";

interface DiscoverRowProps {
  symbol: string;
  name?: string | null;
  price?: string; // pre-formatted, e.g. "$142.50"
  priceAsOf?: string | null; // the quote's own date and time, shown under the price; a price never appears without it
  /** Why this stock is in this section, one sentence (lib/discoverSentences). Wraps; never cut short. */
  sentence: string;
  /** An optional second line under the sentence (the calendar's options-against-typical comparison), already linked. */
  detail?: React.ReactNode;
  /** The row's hover: the figures behind a sentence written in words (the tape's receipt). */
  title?: string;
}

/** One stock on /discover: ticker, company, last price, then the reason. The whole row opens the ticker page. */
export default function DiscoverRow({ symbol, name, price, priceAsOf, sentence, detail, title }: DiscoverRowProps) {
  return (
    <li>
      <Link
        href={`/tickers/${symbol}`}
        title={title}
        className="group block py-3 sm:grid sm:grid-cols-[18rem_minmax(0,1fr)] sm:gap-x-6 hover:bg-muted/40 transition-colors"
      >
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="font-display text-sm font-bold text-foreground group-hover:text-primary transition-colors shrink-0">
            {symbol}
          </span>
          {name && <span className="text-sm text-muted-foreground min-w-0 break-words">{name}</span>}
          {price && priceAsOf && (
            <span className="ml-auto pl-2 font-mono text-xs text-muted-foreground shrink-0 text-right">
              {price}<span className="block text-[10px] text-muted-foreground/60 font-sans">as of {priceAsOf}</span>
            </span>
          )}
        </div>
        <div className="mt-0.5 sm:mt-0 min-w-0">
          <p className="text-sm text-foreground/80 leading-snug break-words">{sentence}</p>
          {detail && <p className="mt-1 text-xs text-muted-foreground leading-snug break-words">{detail}</p>}
        </div>
      </Link>
    </li>
  );
}

/** The list the rows sit in: one column, a hairline between rows. */
export function DiscoverRows({ children }: { children: React.ReactNode }) {
  return <ul className="divide-y divide-border/60">{children}</ul>;
}
