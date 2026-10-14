import type { RangeBand, Verdict } from "@/lib/optionsVerdict";
import ExplainTip from "@/components/ticker/ExplainTip";
import Explained from "@/components/Explained";

const money = (n: number) => `$${n.toFixed(2)}`;

/** Today's price inside the implied low and high by the expiration, as one horizontal band. */
export function RangeBandView({ band }: { band: RangeBand }) {
  const clampLeft = (pos: number) => `clamp(3.25rem, ${pos}%, calc(100% - 3.25rem))`;
  return (
    <figure className="mt-6 max-w-xl" data-testid="range-band">
      <figcaption className="text-xs text-muted-foreground"><ExplainTip term="implied range">Implied range</ExplainTip> by {band.by}</figcaption>
      <div className="relative mt-9 h-2 rounded-full bg-muted">
        <div
          className="absolute inset-y-0 rounded-full bg-primary/30 border-x-2 border-primary"
          style={{ left: `${band.lowPos}%`, width: `${band.highPos - band.lowPos}%` }}
        />
        <div className="absolute -top-2 -bottom-2 w-0.5 -translate-x-1/2 rounded bg-foreground" style={{ left: `${band.markerPos}%` }} />
        <div
          className="absolute bottom-full mb-3 -translate-x-1/2 whitespace-nowrap text-center"
          style={{ left: clampLeft(band.markerPos) }}
        >
          <span className="block text-sm font-semibold tabular-nums text-foreground" data-testid="range-marker">{money(band.marker)}</span>
        </div>
      </div>
      <div className="relative mt-2 h-5 text-sm tabular-nums">
        <span className="absolute -translate-x-1/2 text-foreground" style={{ left: clampLeft(band.lowPos) }} data-testid="range-low">{money(band.low)}</span>
        <span className="absolute -translate-x-1/2 text-foreground" style={{ left: clampLeft(band.highPos) }} data-testid="range-high">{money(band.high)}</span>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">The mark is {money(band.marker)}, the {band.markerLabel}.</p>
    </figure>
  );
}

/** The Options section's opening: the verdict sentence and its band, or one plain line saying why there is none. */
export function OptionsVerdictView({ verdict }: { verdict: Verdict }) {
  if (verdict.kind === "absent") {
    return <p className="text-base text-muted-foreground max-w-2xl" data-testid="options-verdict-absent"><Explained text={verdict.line} /></p>;
  }
  return (
    <div data-testid="options-verdict">
      <p className="text-xl sm:text-2xl font-medium leading-snug text-foreground max-w-2xl" data-testid="options-verdict-sentence"><Explained text={verdict.sentence} /></p>
      {verdict.why && <p className="mt-2 text-sm text-muted-foreground max-w-2xl"><Explained text={verdict.why} /></p>}
      <p className="mt-2 text-xs text-muted-foreground max-w-2xl"><Explained text={verdict.receipt} /></p>
      {verdict.band && <RangeBandView band={verdict.band} />}
    </div>
  );
}
