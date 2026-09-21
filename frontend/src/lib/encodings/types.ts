/** One row of a legend, generated from an encoding config. Never written by hand. */
export interface LegendItem {
  key: string;
  label: string;
  /** What the mark looks like: enough for a swatch to demonstrate it. */
  swatch: {
    kind: "fill" | "line" | "bar" | "pill" | "text";
    color?: string;          // CSS color, for fills, lines and bars
    className?: string;      // tailwind classes, for pills and text
    opacity?: number;
    dashed?: boolean;
  };
}
