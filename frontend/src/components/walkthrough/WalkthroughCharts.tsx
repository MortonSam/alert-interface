"use client";

import { CartesianGrid, Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import EncodingLegend from "@/components/EncodingLegend";
import { peMark, peRangeLegend, priceMark, priceVsMarketLegend, PE_RANGE_ENCODING, type PeMarkKey, type PriceMarkKey } from "@/lib/encodings/walkthroughCharts";
import type { PeChart, PriceChart } from "@/lib/walkthrough";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthTick = (iso: string) => `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(2, 4)}`;
const yearTick = (iso: string) => iso.slice(0, 4);

/** Step 4: the stock, SPY and the median stock of its sector, each indexed to 100 a year ago. */
export function PriceVsMarketChart({ chart, name, sector }: { chart: PriceChart; name: string; sector: string | null }) {
  const byDate = new Map<string, Record<string, number | string>>();
  for (const s of chart.series) for (const [d, v] of s.points) byDate.set(d, { ...(byDate.get(d) ?? { d }), [s.key]: v });
  const rows = [...byDate.values()].sort((a, b) => String(a.d).localeCompare(String(b.d)));
  const keys = chart.series.map((s) => s.key) as PriceMarkKey[];
  return (
    <figure className="mt-5">
      <div className="h-[190px] sm:h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.4} vertical={false} />
            <XAxis dataKey="d" tickFormatter={monthTick} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} minTickGap={36} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} width={44} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
            <ReferenceLine y={100} {...priceMark("base")} />
            {keys.map((k) => (
              <Line key={k} dataKey={k} dot={false} isAnimationActive={false} connectNulls {...priceMark(k)} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <EncodingLegend items={priceVsMarketLegend([...keys, "base"], { name, sector })} className="mt-2" />
    </figure>
  );
}

/** Step 5: the valuation multiple each trading day over five years, its median, the sector median now, and today (chart.points). */
export function PeRangeChart({ chart }: { chart: PeChart }) {
  const rows = chart.points.map(([d, v]) => ({ d, pe: v }));
  const keys: PeMarkKey[] = ["pe", "median", ...(chart.sector_median != null ? (["sectorMedian"] as PeMarkKey[]) : []), "today"];
  const last = rows[rows.length - 1];
  const yearTicks = rows.filter((r, i) => i > 0 && r.d.slice(0, 4) !== rows[i - 1].d.slice(0, 4)).map((r) => r.d);   // one tick at each year's first point
  return (
    <figure className="mt-5">
      <div className="h-[190px] sm:h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.4} vertical={false} />
            <XAxis dataKey="d" ticks={yearTicks} interval={0} tickFormatter={yearTick} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} width={40} axisLine={false} tickLine={false} domain={[0, "auto"]} />
            <ReferenceLine y={chart.median} {...peMark("median")} />
            {chart.sector_median != null && <ReferenceLine y={chart.sector_median} {...peMark("sectorMedian")} />}
            <Line dataKey="pe" dot={false} isAnimationActive={false} {...peMark("pe")} />
            {last && <ReferenceDot x={last.d} y={chart.today} r={4.5} fill={PE_RANGE_ENCODING.today.color} stroke="hsl(var(--background))" strokeWidth={1.5} />}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <EncodingLegend items={peRangeLegend(keys, { sector: chart.sector })} className="mt-2" />
    </figure>
  );
}
