"use client";

import { useEffect, useMemo, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, ReferenceLine, ReferenceArea,
} from "recharts";
import { type StrategyData, type StrikeData } from "@/lib/api";
import { cn } from "@/lib/utils";
import Callout from "@/components/Callout";
import {
  BS_R, BS_IV_DEFAULT, MS_PER_YEAR, dateMs, blackScholes,
} from "@/lib/black-scholes";
import {
  type StrategyType, STRATEGY_META,
  payoffPS, payoffBSPS, strategyStats, PayoffYTick,
} from "./shared";

function PayoffTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{
    name: string;
    dataKey: string;
    value: number;
    color: string;
    payload: { price: number };
  }>;
}) {
  if (!active || !payload?.length) return null;
  const price = payload[0].payload.price;
  return (
    <div className="rounded border bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100 shadow px-3 py-2 text-xs space-y-0.5">
      <p className="text-zinc-500 dark:text-zinc-400">Stock: <strong className="text-zinc-900 dark:text-zinc-100">${price.toFixed(2)}</strong></p>
      {payload.filter(p => p.value != null).map((p) => {
        const abs = Math.abs(p.value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return (
          <p key={p.dataKey} style={{ color: p.color }} className="font-medium">
            {p.name}: {p.value >= 0 ? "+" : "\u2212"}${abs}
          </p>
        );
      })}
    </div>
  );
}

export default function StrategyCard({
  strategy,
  data,
}: {
  strategy: StrategyType;
  data: StrategyData;
}) {
  const meta = STRATEGY_META[strategy];
  const cp = data.current_price ?? 0;

  const validStrikes = useMemo<StrikeData[]>(() => {
    return data.strikes
      .filter((s) => (meta.usesCall ? s.call_mid != null : s.put_mid != null))
      .sort((a, b) => a.strike - b.strike);
  }, [data.strikes, meta.usesCall]);

  const initialStrike = useMemo(() => {
    const atm = validStrikes.find((s) => s.is_atm);
    return atm?.strike ?? validStrikes[Math.floor(validStrikes.length / 2)]?.strike ?? 0;
  }, [validStrikes]);

  const [selectedStrike, setSelectedStrike] = useState<number>(initialStrike);
  const [contracts, setContracts] = useState<number>(1);
  const [dateOffset, setDateOffset] = useState<number>(0); // 0 = today, totalDays = expiry
  const [scrubPrice, setScrubPrice] = useState<number>(cp);

  useEffect(() => {
    setSelectedStrike(initialStrike);
  }, [initialStrike]);

  const strikeObj = validStrikes.find((s) => s.strike === selectedStrike);
  const premium = (meta.usesCall ? strikeObj?.call_mid : strikeObj?.put_mid) ?? 0;

  // IV for BS pricing: use per-strike IV, fall back to ATM IV, then a default
  const atmIVData = data.strikes.find((s) => s.is_atm);
  const sigma = (
    meta.usesCall
      ? (strikeObj?.call_iv ?? atmIVData?.call_iv ?? BS_IV_DEFAULT)
      : (strikeObj?.put_iv  ?? atmIVData?.put_iv  ?? BS_IV_DEFAULT)
  );

  const T_today = data.expiration
    ? Math.max(0, (dateMs(data.expiration) - Date.now()) / MS_PER_YEAR)
    : 0;
  const T_earnings = (data.earnings_date && data.expiration)
    ? Math.max(0, (dateMs(data.expiration) - dateMs(data.earnings_date)) / MS_PER_YEAR)
    : null;
  const showEarnings = T_earnings !== null && T_earnings > 0 && T_earnings < T_today;

  // Date slider: 0=today → totalDays=expiry; T_slider is T at the selected date
  const totalDays = Math.max(1, Math.round(T_today * 365.25));
  const T_slider = Math.max(0, (totalDays - dateOffset) / 365.25);
  const selectedDateMs = Date.now() + dateOffset * 86400000;
  const selectedDateStr = new Date(selectedDateMs).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const daysToExpiry = Math.max(0, totalDays - dateOffset);
  const earningsDateMs = data.earnings_date ? dateMs(data.earnings_date) : null;
  // Disclaimer: show whenever the slider is at or before earnings (IV held constant is misleading then)
  const showDisclaimer = showEarnings && earningsDateMs != null && selectedDateMs <= earningsDateMs;

  const mult = contracts * 100;

  // x-axis range: implied range ± 30% of range width, extended if breakeven falls outside
  const xRange = useMemo(() => {
    const irLo = data.implied_range_low;
    const irHi = data.implied_range_high;
    let lo: number, hi: number;
    if (irLo != null && irHi != null) {
      const pad = (irHi - irLo) * 0.30;
      lo = irLo - pad;
      hi = irHi + pad;
    } else {
      lo = cp * 0.80;
      hi = cp * 1.20;
    }
    // Extend if the strategy's breakeven would fall outside the frame
    const beValues: number[] = [];
    if (strategy === "long_call")    beValues.push(selectedStrike + premium);
    if (strategy === "long_put")     beValues.push(selectedStrike - premium);
    if (strategy === "covered_call") beValues.push(cp - premium);
    if (strategy === "csp")          beValues.push(selectedStrike - premium);
    for (const be of beValues) {
      if (be < lo) lo = be - (hi - lo) * 0.05;
      if (be > hi) hi = be + (hi - lo) * 0.05;
    }
    return { lo, hi };
  }, [data.implied_range_low, data.implied_range_high, cp, strategy, selectedStrike, premium]);

  // Live chartData: recomputes on every slider tick (~100 BS evals, <1 ms)
  const chartData = useMemo(() => {
    if (!cp) return [];
    const { lo, hi } = xRange;
    return Array.from({ length: 100 }, (_, i) => {
      const S = lo + (i / 99) * (hi - lo);
      const pnl = T_slider > 0
        ? payoffBSPS(strategy, selectedStrike, premium, cp, S, T_slider, sigma, BS_R, blackScholes) * mult
        : payoffPS(strategy, selectedStrike, premium, cp, S) * mult;
      return { price: parseFloat(S.toFixed(2)), pnl: parseFloat(pnl.toFixed(2)) };
    });
  }, [strategy, selectedStrike, premium, cp, mult, xRange, T_slider, sigma]);

  const stats = useMemo(
    () => strategyStats(strategy, selectedStrike, premium, cp),
    [strategy, selectedStrike, premium, cp],
  );

  if (!validStrikes.length || !cp) {
    return (
      <div className="rounded-lg border bg-card px-5 py-4 text-sm text-muted-foreground">
        No valid contracts available for {meta.name}.
      </div>
    );
  }

  // Stable Y-axis: computed from expiry+today endpoints so axis doesn't jump as slider moves
  const yDomain = useMemo<[number, number]>(() => {
    if (!cp) return [-100, 100];
    const { lo, hi } = xRange;
    const vals: number[] = [];
    for (let i = 0; i < 100; i++) {
      const S = lo + (i / 99) * (hi - lo);
      vals.push(payoffPS(strategy, selectedStrike, premium, cp, S) * mult);
      if (T_today > 0) vals.push(payoffBSPS(strategy, selectedStrike, premium, cp, S, T_today, sigma, BS_R, blackScholes) * mult);
    }
    const yMin = Math.min(...vals);
    const yMax = Math.max(...vals);
    const pad = (yMax - yMin) * 0.15 || 1;
    return [yMin - pad, yMax + pad];
  }, [strategy, selectedStrike, premium, cp, mult, xRange, T_today, sigma]);

  const xLo = chartData[0]?.price ?? 0;
  const xHi = chartData[chartData.length - 1]?.price ?? 0;
  const scrubPoint = chartData.length
    ? chartData.reduce((best, d) => Math.abs(d.price - scrubPrice) < Math.abs(best.price - scrubPrice) ? d : best)
    : null;
  const effectivePrice = scrubPoint?.price ?? scrubPrice;
  const scrubPnl: number | null = scrubPoint?.pnl ?? null;

  return (
    <div className="rounded-lg border bg-card px-5 py-4 space-y-3">
      <div>
        <h4 className="font-semibold text-sm">{meta.name}</h4>
        <p className="text-xs text-muted-foreground mt-0.5">{meta.oneLiner}</p>
      </div>

      <p className="text-sm text-muted-foreground leading-relaxed">{meta.description}</p>

      {/* Strike + contracts selectors */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground shrink-0">Strike:</span>
          <select
            value={selectedStrike}
            onChange={(e) => setSelectedStrike(parseFloat(e.target.value))}
            className="rounded-md border bg-background px-2 py-1 text-sm"
          >
            {validStrikes.map((s) => {
              const mid = meta.usesCall ? s.call_mid : s.put_mid;
              return (
                <option key={s.strike} value={s.strike}>
                  ${s.strike.toFixed(0)}{s.is_atm ? " (ATM)" : ""}{" "}
                  — {meta.usesCall ? "call" : "put"} ${mid?.toFixed(2) ?? "\u2014"}
                </option>
              );
            })}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground shrink-0">Contracts:</span>
          <input
            type="number"
            min={1}
            max={500}
            value={contracts}
            onChange={(e) => setContracts(Math.max(1, parseInt(e.target.value) || 1))}
            className="rounded-md border bg-background px-2 py-1 text-sm w-16 tabular-nums"
          />
        </div>
        {data.expiration && (
          <span className="text-xs text-muted-foreground">expiry {data.expiration}</span>
        )}
      </div>

      {/* ── Hero P&L ──────────────────────────────────────────────── */}
      <div className="py-1">
        <p className="text-xs text-muted-foreground mb-1.5">
          {data.symbol} at ${effectivePrice.toFixed(2)}
          {" \u00b7 "}
          {daysToExpiry === 0 ? "At expiration" : selectedDateStr}
        </p>
        <p className={cn(
          "text-4xl font-bold tabular-nums tracking-tight leading-none",
          scrubPnl == null
            ? "text-muted-foreground"
            : scrubPnl >= 0
              ? "text-success"
              : "text-destructive",
        )}>
          {scrubPnl == null
            ? "\u2014"
            : `${scrubPnl >= 0 ? "+" : "\u2212"}$${Math.abs(scrubPnl).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
        </p>
      </div>

      {/* ── Live payoff chart ──────────────────────────────────────── */}
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

          {/* Implied range band — very faint */}
          {data.implied_range_low != null && data.implied_range_high != null && (
            <ReferenceArea
              x1={Math.max(data.implied_range_low, xLo)}
              x2={Math.min(data.implied_range_high, xHi)}
              fill="hsl(var(--muted))"
              fillOpacity={0.2}
            />
          )}

          {/* Zero line */}
          <ReferenceLine y={0} stroke="hsl(var(--border))" strokeWidth={1} />

          {/* Current price */}
          <ReferenceLine
            x={cp}
            stroke="hsl(var(--muted-foreground))"
            strokeWidth={1}
            strokeDasharray="3 5"
            strokeOpacity={0.6}
            label={{ value: "Current", position: "insideBottomRight", fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
          />

          {/* Price scrubber */}
          <ReferenceLine
            x={effectivePrice}
            stroke="hsl(var(--foreground))"
            strokeWidth={1.5}
            strokeOpacity={0.85}
          />

          {/* Breakeven(s) */}
          {stats.breakevens.map((be, i) => (
            <ReferenceLine
              key={i}
              x={be}
              stroke="hsl(var(--success))"
              strokeWidth={1}
              strokeDasharray="3 5"
              strokeOpacity={0.8}
              label={{ value: "B/E", position: "insideTopRight", fontSize: 9, fill: "hsl(var(--success))" }}
            />
          ))}

          {/* P&L curve — redraws live with each slider tick */}
          <Line
            dataKey="pnl"
            stroke="hsl(var(--cool))"
            strokeWidth={2.5}
            dot={false}
            activeDot={false}
            type={T_slider === 0 ? "linear" : "monotone"}
            isAnimationActive={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>

      {/* ── Date slider ────────────────────────────────────────────── */}
      <div className="space-y-1.5 px-0.5">
        <input
          type="range"
          min={0}
          max={totalDays}
          value={dateOffset}
          onChange={(e) => setDateOffset(parseInt(e.target.value))}
          className="w-full h-1 rounded-full appearance-none cursor-pointer"
          style={{ accentColor: "hsl(var(--foreground))" }}
        />
        <div className="flex justify-between items-baseline text-[10px]">
          <span className="text-muted-foreground">Today</span>
          <span className="font-medium text-foreground">
            {daysToExpiry === 0
              ? "At expiration"
              : `${selectedDateStr} \u00b7 ${daysToExpiry}d to expiry`}
          </span>
          <span className="text-muted-foreground">Expiry</span>
        </div>
      </div>

      {/* IV-crush disclaimer — shows when slider is at or before earnings date */}
      {showDisclaimer && (
        <Callout severity="info" compact>
          This curve holds today&apos;s implied volatility constant.
          In practice, IV typically collapses after an earnings release — option values at
          or around earnings will likely be lower than shown.
        </Callout>
      )}

      {/* Key stats — dollar figures scaled to contract size; breakeven stays as stock price */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm pt-1 border-t">
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">Premium {meta.usesCall ? "paid" : "received"}:</span>
          <span className="font-medium tabular-nums">
            ${(premium * mult).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>
        {stats.breakevens.map((be, i) => (
          <div key={i} className="flex justify-between gap-2">
            <span className="text-muted-foreground">Breakeven (stock price):</span>
            <span className="font-medium tabular-nums">${be.toFixed(2)}</span>
          </div>
        ))}
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">Max gain:</span>
          <span className="font-medium tabular-nums text-green-600 dark:text-green-400">
            {stats.maxGain == null
              ? "Unlimited \u2191"
              : `+$${(stats.maxGain * mult).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          </span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">Max loss:</span>
          <span className="font-medium tabular-nums text-red-600 dark:text-red-400">
            {"\u2212"}${(stats.maxLoss * mult).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>
      </div>
    </div>
  );
}
