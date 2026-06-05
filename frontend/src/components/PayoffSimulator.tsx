"use client";

import { useEffect, useMemo, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import {
  BS_R,
  type Leg,
  multiLegPayoffPS,
  multiLegPayoffBSPS,
} from "@/lib/black-scholes";

// ── Chart helpers ─────────────────────────────────────────────────────────────

type ChartPoint = {
  price: number;
  pnl: number;
  pnl_pos: number | null;   // pnl when >= 0, else null  → green line
  pnl_neg: number | null;   // pnl when <  0, else null  → red line
};

/**
 * Split raw {price,pnl} series into green/red segments.
 * Inserts interpolated zero-crossing points so the two lines meet precisely at
 * pnl=0 without a gap or a diagonal bridge.
 */
function splitBySign(raw: Array<{ price: number; pnl: number }>): ChartPoint[] {
  const out: ChartPoint[] = [];
  for (let i = 0; i < raw.length; i++) {
    const d = raw[i];
    const prev = raw[i - 1];
    // Insert zero-crossing between prev and d when they straddle zero
    if (prev && d.pnl !== 0 && prev.pnl !== 0 && Math.sign(d.pnl) !== Math.sign(prev.pnl)) {
      const t = prev.pnl / (prev.pnl - d.pnl);   // interpolation fraction [0,1]
      const crossPrice = parseFloat((prev.price + t * (d.price - prev.price)).toFixed(2));
      out.push({ price: crossPrice, pnl: 0, pnl_pos: 0, pnl_neg: 0 });
    }
    out.push({
      price:   d.price,
      pnl:     d.pnl,
      pnl_pos: d.pnl >= 0 ? d.pnl : null,
      pnl_neg: d.pnl <  0 ? d.pnl : null,
    });
  }
  return out;
}

// ── PayoffYTick ───────────────────────────────────────────────────────────────

function PayoffYTick({
  x, y, payload,
}: {
  x?: number;
  y?: number;
  payload?: { value: number };
}) {
  if (x == null || y == null || !payload) return null;
  const v = payload.value;
  const color = v < 0 ? "#dc2626" : v > 0 ? "#16a34a" : "hsl(var(--muted-foreground))";
  const abs = Math.abs(Math.round(v)).toLocaleString("en-US");
  const label = v >= 0 ? `+$${abs}` : `-$${abs}`;
  return (
    <text x={x} y={y} fill={color} fontSize={10} textAnchor="end" dominantBaseline="middle">
      {label}
    </text>
  );
}

// ── SimTooltip ────────────────────────────────────────────────────────────────
// Reads .pnl from the raw data point (not from a series value) so it works
// regardless of which of the two colored Lines triggered the hover.

function SimTooltip({
  active, payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: ChartPoint }>;
}) {
  if (!active || !payload?.length) return null;
  const pt = payload[0]?.payload;
  if (!pt) return null;
  const { price, pnl } = pt;
  const abs = Math.abs(pnl).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (
    <div className="rounded border bg-card border-border text-foreground shadow px-3 py-2 text-xs space-y-0.5">
      <p className="text-muted-foreground">
        Stock: <strong className="text-foreground">${price.toFixed(2)}</strong>
      </p>
      <p className={`font-medium ${pnl >= 0 ? "text-success" : "text-destructive"}`}>
        Simulated: {pnl >= 0 ? "+" : "−"}${abs}
      </p>
    </div>
  );
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface PayoffSimulatorProps {
  legs: Leg[];               // each leg's sigma is a 0–1 decimal; mid is per-share premium
  spot: number;              // resolved starting price (non-null); initial scrub position
  currentPrice: number | null; // live market price for "Current" reference line; may be null
  symbol: string;            // ticker symbol for hero P&L label
  expirationMs: number;      // ms timestamp of the expiration date (via dateMs())
  mult: number;              // position multiplier = contracts * 100
  xMin: number;              // x-axis lower bound, already fallback-resolved by caller
  xMax: number;              // x-axis upper bound, already fallback-resolved by caller
  earningsMs: number | null; // for the IV-crush caveat; null = no caveat
  usingIVFallback: boolean;  // true if any IV came from BS_IV_DEFAULT
  sdFailed: boolean;         // true if strategyData fetch failed (different warning message)
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function PayoffSimulator({
  legs, spot, currentPrice, symbol, expirationMs, mult, xMin, xMax,
  earningsMs, usingIVFallback, sdFailed,
}: PayoffSimulatorProps) {

  const nowMs = Date.now();
  const daysToExpiry = Math.max(0, Math.round((expirationMs - nowMs) / 86400000));
  const totalDays = Math.max(1, daysToExpiry);

  const [dateOffset, setDateOffset] = useState(0);
  const [scrubPrice, setScrubPrice] = useState<number>(spot);

  useEffect(() => {
    setScrubPrice(spot);
  }, [spot]);

  const T_slider = Math.max(0, (totalDays - dateOffset) / 365.25);
  const selectedDateMs = nowMs + dateOffset * 86400000;
  const selectedDateStr = new Date(selectedDateMs).toLocaleDateString("en-US", {
    month: "short", day: "numeric",
  });
  const daysLeft = Math.max(0, totalDays - dateOffset);

  const showDisclaimer = earningsMs != null && selectedDateMs <= earningsMs;

  // IV label (computed from leg sigmas; sigma is already 0–1 decimal)
  const ivLabel = useMemo(() => {
    if (legs.length === 1) return `${(legs[0].sigma * 100).toFixed(1)}%`;
    const ivs = legs.map(l => `${l.label.split(" ")[0]} ${l.label.split(" ")[1]}: ${(l.sigma * 100).toFixed(1)}%`);
    return ivs.join(" · ");
  }, [legs]);

  // Chart data — split into green/red segments at the zero crossover
  const chartData = useMemo((): ChartPoint[] => {
    const raw = Array.from({ length: 100 }, (_, i) => {
      const S = xMin + (i / 99) * (xMax - xMin);
      const pnl = multiLegPayoffBSPS(legs, S, T_slider, BS_R) * mult;
      return { price: parseFloat(S.toFixed(2)), pnl: parseFloat(pnl.toFixed(2)) };
    });
    return splitBySign(raw);
  }, [legs, xMin, xMax, T_slider, mult]);

  // Stable y-domain (computed from at-expiry + today curves so axis doesn't jump while sliding)
  const yDomain = useMemo<[number, number]>(() => {
    const vals: number[] = [];
    for (let i = 0; i < 100; i++) {
      const S = xMin + (i / 99) * (xMax - xMin);
      vals.push(multiLegPayoffPS(legs, S) * mult);
      if (daysToExpiry > 0) {
        vals.push(multiLegPayoffBSPS(legs, S, daysToExpiry / 365.25, BS_R) * mult);
      }
    }
    const yMin = Math.min(...vals);
    const yMax = Math.max(...vals);
    const pad = (yMax - yMin) * 0.15 || 10;
    return [yMin - pad, yMax + pad];
  }, [legs, xMin, xMax, daysToExpiry, mult]);

  const scrubPoint = chartData.length
    ? chartData.reduce((best, d) =>
        Math.abs(d.price - scrubPrice) < Math.abs(best.price - scrubPrice) ? d : best)
    : null;
  const effectivePrice = scrubPoint?.price ?? scrubPrice;
  const scrubPnl: number | null = scrubPoint?.pnl ?? null;

  // ── Date slider geometry ──────────────────────────────────────────────────
  // thumbPct: 0% (Today) → 100% (Expiry), used for the visual fill + floating label
  const thumbPct = totalDays > 0 ? (dateOffset / totalDays) * 100 : 0;
  // Clamp label so it doesn't overflow the container at extremes
  const labelLeft = Math.max(7, Math.min(93, thumbPct));
  // What to show in the floating thumb label
  const thumbLabel = dateOffset === 0
    ? "Today"
    : daysLeft === 0
      ? "At expiry"
      : `${selectedDateStr} · ${daysLeft}d`;

  // "Expiry Jun 5" label for slider endpoint — derived from expirationMs
  const expiryLabel = new Date(expirationMs).toLocaleDateString("en-US", {
    month: "short", day: "numeric",
  });

  return (
    <div className="rounded-lg border border-dashed bg-muted/20 px-5 py-4 space-y-3">

      {/* Header pill — stays prominent so "this is modeled" is always clear */}
      <div className="flex items-center gap-2">
        <span className="bg-cool/10 text-cool border border-cool/40 text-xs font-medium px-2 py-0.5 rounded-full">
          SIMULATED
        </span>
        <span className="text-xs text-muted-foreground">Black-Scholes projection</span>
      </div>

      {/* IV disclosure — always show what IV the simulation holds constant */}
      {ivLabel && !sdFailed && !usingIVFallback && (
        <p className="text-xs text-muted-foreground">
          Simulated at IV {ivLabel} (held constant)
        </p>
      )}
      {(sdFailed || usingIVFallback) && (
        <p className="text-[11px] leading-relaxed text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded-md px-3 py-2">
          <strong>
            {sdFailed
              ? "Could not load current IV for this strike — simulation uses a 30% default and may be inaccurate."
              : "IV for one or more strikes not found — simulation uses a 30% default and may be inaccurate."}
          </strong>{" "}
          Real IV may differ significantly (e.g. high-vol names can be 50–80%).
        </p>
      )}

      {/* Hero simulated P&L */}
      <div className="py-1">
        <p className="text-xs text-muted-foreground mb-1.5">
          {symbol} at ${effectivePrice.toFixed(2)}
          {" · "}
          {daysLeft === 0 ? "At expiration" : selectedDateStr}
        </p>
        <p className={[
          "text-4xl font-bold font-mono tabular-nums tracking-tight leading-none",
          scrubPnl == null
            ? "text-muted-foreground"
            : scrubPnl >= 0
              ? "text-success"
              : "text-destructive",
        ].join(" ")}>
          {scrubPnl == null
            ? "—"
            : `${scrubPnl >= 0 ? "+" : "−"}$${Math.abs(scrubPnl).toLocaleString("en-US", {
                minimumFractionDigits: 2, maximumFractionDigits: 2,
              })}`}
        </p>
      </div>

      {/* ── Payoff chart ──────────────────────────────────────────────────── */}
      {chartData.length > 0 && (
        <div className="relative">
          {/* SIMULATED watermark — keeps the "this is modeled" signal in the chart itself */}
          <div
            className="absolute inset-0 flex items-center justify-center pointer-events-none select-none"
            style={{ zIndex: 1 }}
          >
            <span className="text-[11px] font-semibold tracking-widest text-cool/20 uppercase">
              Simulated
            </span>
          </div>

          <ResponsiveContainer width="100%" height={200}>
            <LineChart
              data={chartData}
              margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
              onMouseMove={(e) => {
                if (e.activeLabel != null) {
                  const p = parseFloat(String(e.activeLabel));
                  if (!isNaN(p)) setScrubPrice(p);
                }
              }}
              onClick={(e) => {
                if (e.activeLabel != null) {
                  const p = parseFloat(String(e.activeLabel));
                  if (!isNaN(p)) setScrubPrice(p);
                }
              }}
            >
              <CartesianGrid
                strokeDasharray="2 6"
                stroke="hsl(var(--border))"
                strokeOpacity={0.4}
                vertical={false}
              />
              <XAxis
                dataKey="price"
                type="number"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                domain={yDomain}
                tick={<PayoffYTick />}
                axisLine={false}
                tickLine={false}
                width={68}
              />
              <Tooltip content={<SimTooltip />} />

              {/* Zero line */}
              <ReferenceLine y={0} stroke="hsl(var(--border))" strokeWidth={1} />

              {/* Current price marker */}
              {currentPrice != null && (
                <ReferenceLine
                  x={currentPrice}
                  stroke="hsl(var(--muted-foreground))"
                  strokeWidth={1}
                  strokeDasharray="3 5"
                  strokeOpacity={0.6}
                  label={{ value: "Current", position: "insideBottomRight", fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
                />
              )}

              {/* Price scrubber */}
              <ReferenceLine
                x={effectivePrice}
                stroke="hsl(var(--cool))"
                strokeWidth={1.5}
                strokeOpacity={0.7}
              />

              {/* Green: profit zone (pnl >= 0) */}
              <Line
                dataKey="pnl_pos"
                stroke="#16a34a"
                strokeWidth={2.5}
                dot={false}
                activeDot={false}
                type={T_slider === 0 ? "linear" : "monotone"}
                isAnimationActive={false}
                connectNulls={false}
              />
              {/* Red: loss zone (pnl < 0) */}
              <Line
                dataKey="pnl_neg"
                stroke="#dc2626"
                strokeWidth={2.5}
                dot={false}
                activeDot={false}
                type={T_slider === 0 ? "linear" : "monotone"}
                isAnimationActive={false}
                connectNulls={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Date slider ───────────────────────────────────────────────────── */}
      <div className="pt-2">
        {/*
         * Custom overlay slider:
         *   - Floating pill label above the thumb shows the selected date + DTE
         *   - Filled indigo track from Today → thumb
         *   - "Today" tick (left) and "Expiry DATE" tick (right) are always visible
         *   - Native <input type="range"> overlaid invisibly handles all interactions
         */}

        {/* Floating thumb label — rides with the handle */}
        <div className="relative h-7 mb-0.5 pointer-events-none select-none">
          <div
            className="absolute bottom-1 -translate-x-1/2 transition-none"
            style={{ left: `${labelLeft}%` }}
          >
            <div className="bg-cool text-cool-foreground text-[10px] font-semibold px-2 py-0.5 rounded-full whitespace-nowrap shadow-sm">
              {thumbLabel}
            </div>
            {/* Connector line from pill to thumb */}
            <div className="flex justify-center mt-0.5">
              <div className="w-px h-1.5 bg-cool rounded-full" />
            </div>
          </div>
        </div>

        {/* Track + visual thumb + invisible native input */}
        <div className="relative h-5 flex items-center">
          {/* Track background */}
          <div className="absolute inset-x-0 h-1.5 rounded-full bg-border pointer-events-none" />
          {/* Filled portion — Today → thumb */}
          <div
            className="absolute left-0 h-1.5 rounded-full bg-cool pointer-events-none transition-none"
            style={{ width: `${thumbPct}%` }}
          />
          {/* Visual thumb circle */}
          <div
            className="absolute w-4 h-4 rounded-full bg-cool shadow ring-2 ring-background pointer-events-none transition-none"
            style={{ left: `${thumbPct}%`, transform: "translateX(-50%)" }}
          />
          {/* Native input — transparent overlay, handles all drag interactions */}
          <input
            type="range"
            min={0}
            max={totalDays}
            value={dateOffset}
            onChange={(e) => setDateOffset(parseInt(e.target.value))}
            className="absolute inset-0 w-full opacity-0 cursor-pointer"
          />
        </div>

        {/* Endpoint labels with tick marks */}
        <div className="flex justify-between items-start mt-1.5 text-[10px] text-muted-foreground">
          <div className="flex flex-col items-center gap-0.5">
            <div className="w-px h-2 bg-border rounded-full" />
            <span className="font-medium">Today</span>
          </div>
          <div className="flex flex-col items-center gap-0.5">
            <div className="w-px h-2 bg-border rounded-full" />
            <span>Expiry {expiryLabel}</span>
          </div>
        </div>
      </div>

      {/* IV-crush caveat */}
      {showDisclaimer && (
        <p className="text-[11px] leading-relaxed text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded-md px-3 py-2">
          <strong>Note:</strong> This curve holds today&apos;s implied volatility constant.
          In practice, IV typically collapses after an earnings release — option values at
          or around earnings will likely be lower than shown.
        </p>
      )}

      {/* Footnote — keeps the "not a forecast" label visible at all times */}
      <p className="text-[10px] text-muted-foreground">
        Simulated values use Black-Scholes with IV held constant — not a forecast.
      </p>
    </div>
  );
}
