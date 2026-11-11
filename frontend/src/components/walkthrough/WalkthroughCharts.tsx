"use client";

import { CartesianGrid, Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import EncodingLegend from "@/components/EncodingLegend";
import { peMark, peRangeLegend, priceMark, priceVsMarketLegend, PE_RANGE_ENCODING, type PeMarkKey, type PriceMarkKey } from "@/lib/encodings/walkthroughCharts";
import type { PeChart, PriceChart } from "@/lib/walkthrough";
import { monthLabel, monthTicks, timeRows, yearLabel, yearTicks } from "@/lib/walkthroughAxis";

// Both charts plot points at their dates (a true time axis, lib/walkthroughAxis): a year takes a year's width, and a stretch with no
// points is a gap in the line.

/** Step 4: the stock, SPY and the median stock of its sector, each indexed to 100 a year ago. */
export function PriceVsMarketChart({ chart, name, sector }: { chart: PriceChart; name: string; sector: string | null }) {
  const byDate = new Map<string, Record<string, number | string>>();
  for (const s of chart.series) for (const [d, v] of s.points) byDate.set(d, { ...(byDate.get(d) ?? { d }), [s.key]: v });
  const keys = chart.series.map((s) => s.key) as PriceMarkKey[];
  const rows = timeRows([...byDate.values()] as { d: string }[], keys);
  const domain: [number, number] = [rows[0]?.t ?? 0, rows[rows.length - 1]?.t ?? 0];
  return (
    <figure className="mt-5">
      <div className="h-[190px] sm:h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.4} vertical={false} />
            <XAxis dataKey="t" type="number" scale="time" domain={domain} ticks={monthTicks(domain[0], domain[1])} interval={0} tickFormatter={monthLabel} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} width={44} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
            <ReferenceLine y={100} {...priceMark("base")} />
            {keys.map((k) => (
              <Line key={k} dataKey={k} dot={false} isAnimationActive={false} connectNulls={false} {...priceMark(k)} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <EncodingLegend items={priceVsMarketLegend([...keys, "base"], { name, sector })} className="mt-2" />
    </figure>
  );
}

/** Step 5: the valuation multiple each trading day over the step's window, that window's median (named by the API), the sector median now, and today (chart.points). */
export function PeRangeChart({ chart }: { chart: PeChart }) {
  const rows = timeRows(chart.points.map(([d, v]) => ({ d, pe: v as number | null })), ["pe"]);
  const keys: PeMarkKey[] = ["pe", "median", ...(chart.sector_median != null ? (["sectorMedian"] as PeMarkKey[]) : []), "today"];
  const last = rows[rows.length - 1];
  const domain: [number, number] = [rows[0]?.t ?? 0, last?.t ?? 0];
  return (
    <figure className="mt-5">
      <div className="h-[190px] sm:h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.4} vertical={false} />
            <XAxis dataKey="t" type="number" scale="time" domain={domain} ticks={yearTicks(domain[0], domain[1])} interval={0} tickFormatter={yearLabel} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} width={40} axisLine={false} tickLine={false} domain={[0, "auto"]} tickFormatter={(v: number) => `$${v}`} />
            <ReferenceLine y={chart.median} {...peMark("median")} />
            {chart.sector_median != null && <ReferenceLine y={chart.sector_median} {...peMark("sectorMedian")} />}
            <Line dataKey="pe" dot={false} isAnimationActive={false} connectNulls={false} {...peMark("pe")} />
            {last && <ReferenceDot x={last.t} y={chart.today} r={4.5} fill={PE_RANGE_ENCODING.today.color} stroke="hsl(var(--background))" strokeWidth={1.5} />}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <EncodingLegend items={peRangeLegend(keys, { sector: chart.sector, median: chart.median_label })} className="mt-2" />
    </figure>
  );
}
