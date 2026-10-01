import Link from "next/link";

interface DiscoverRowProps {
  symbol: string;
  name?: string | null;
  price?: string; // pre-formatted, e.g. "$142.50"
  /** Why this stock is in this section, one sentence (lib/discoverSentences). Wraps; never cut short. */
  sentence: string;
}

/** One stock on /discover: ticker, company, last price, then the reason. The whole row opens the ticker page. */
export default function DiscoverRow({ symbol, name, price, sentence }: DiscoverRowProps) {
  return (
    <li>
      <Link
        href={`/tickers/${symbol}`}
        className="group block py-3 sm:grid sm:grid-cols-[18rem_minmax(0,1fr)] sm:gap-x-6 hover:bg-muted/40 transition-colors"
      >
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="font-display text-sm font-bold text-foreground group-hover:text-primary transition-colors shrink-0">
            {symbol}
          </span>
          {name && <span className="text-sm text-muted-foreground min-w-0 break-words">{name}</span>}
          {price && <span className="ml-auto pl-2 font-mono text-xs text-muted-foreground shrink-0">{price}</span>}
        </div>
        <p className="mt-0.5 sm:mt-0 text-sm text-foreground/80 leading-snug break-words">{sentence}</p>
      </Link>
    </li>
  );
}

/** The list the rows sit in: one column, a hairline between rows. */
export function DiscoverRows({ children }: { children: React.ReactNode }) {
  return <ul className="divide-y divide-border/60">{children}</ul>;
}
