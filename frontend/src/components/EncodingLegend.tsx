import type { LegendItem } from "@/lib/encodings/types";

/** A swatch that looks like the mark it names: same color, opacity and dash. */
export function LegendSwatch({ swatch }: { swatch: LegendItem["swatch"] }) {
  const { kind, color, className, opacity, dashed } = swatch;
  if (kind === "line") {
    return (
      <span
        className="inline-block w-4 align-middle"
        style={{ borderTopWidth: 2, borderTopStyle: dashed ? "dashed" : "solid", borderTopColor: color, opacity }}
      />
    );
  }
  if (kind === "bar") {
    // A miniature bar: the fill carries the opacity, the outline stays full strength so dashes read.
    return (
      <span
        className="relative inline-block align-middle"
        style={{ width: 9, height: 14, outline: dashed ? `1.5px dashed ${color}` : "none", outlineOffset: 0, borderRadius: 1 }}
      >
        <span className="absolute inset-0" style={{ backgroundColor: color, opacity, borderRadius: 1 }} />
      </span>
    );
  }
  if (kind === "pill") {
    return <span className={`inline-block rounded px-1.5 py-0.5 text-[9px] leading-none ${className ?? ""}`}>Aa</span>;
  }
  if (kind === "text") {
    return <span className={`font-mono text-[10px] ${className ?? ""}`}>Aa</span>;
  }
  return <span className="inline-block w-2.5 h-2.5 rounded-sm align-middle" style={{ backgroundColor: color, opacity }} />;
}

export default function EncodingLegend({ items, className }: { items: LegendItem[]; className?: string }) {
  return (
    <div className={`flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-muted-foreground ${className ?? ""}`}>
      {items.map((item) => (
        <span key={item.key} className="flex items-center gap-1.5">
          <LegendSwatch swatch={item.swatch} />
          {item.label}
        </span>
      ))}
    </div>
  );
}
