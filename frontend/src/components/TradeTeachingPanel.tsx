"use client";

// Build a Trade's "What this trade does" (lib/tradeTeaching, words from lib/tradeTeachingCopy): what the trade is, in the
// trade's own figures, above the cost cards. Each glossary term is explained at its first use in the panel only.
import { Fragment } from "react";
import ExplainTip from "@/components/ticker/ExplainTip";
import { explainSegments, type Segment } from "@/lib/explainSegments";
import { teachPanel, type TeachLeg } from "@/lib/tradeTeaching";
import { PANEL_TITLE } from "@/lib/tradeTeachingCopy";

/** Pure: each text's segments with a term kept only at its first use across all of them (later uses are plain text). */
export function firstUses(texts: string[]): Segment[][] {
  const seen = new Set<string>();
  return texts.map((t) => explainSegments(t).map((seg) => {
    if (!seg.key || seen.has(seg.key)) return { text: seg.text, key: null };
    seen.add(seg.key);
    return seg;
  }));
}

function Segs({ segs }: { segs: Segment[] }) {
  return <>{segs.map((s, i) => (s.key ? <ExplainTip key={i} term={s.key}>{s.text}</ExplainTip> : <Fragment key={i}>{s.text}</Fragment>))}</>;
}

export default function TradeTeachingPanel({ symbol, legs, expires }: { symbol: string; legs: TeachLeg[]; expires: string }) {
  const panel = teachPanel(symbol, legs, expires);
  const segs = firstUses([...panel.lines, panel.expirationLine, ...panel.regions, panel.closing]);
  const lines = segs.slice(0, panel.lines.length), atExp = segs[panel.lines.length];
  const regions = segs.slice(panel.lines.length + 1, -1), closing = segs[segs.length - 1];
  return (
    <section className="rounded-md border border-border/60 p-5 space-y-3 text-sm leading-relaxed" data-testid="trade-teaching">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{PANEL_TITLE}</p>
      {lines.map((l, i) => <p key={i} className={i === 0 ? "text-foreground" : "text-foreground/85"}><Segs segs={l} /></p>)}
      <div>
        <p className="text-foreground/85"><Segs segs={atExp} /></p>
        <ul className="mt-1.5 space-y-1 list-disc pl-5 text-foreground/85">
          {regions.map((r, i) => <li key={i}><Segs segs={r} /></li>)}
        </ul>
      </div>
      <p className="text-foreground/85"><Segs segs={closing} /></p>
    </section>
  );
}
