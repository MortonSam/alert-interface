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
  BS_R, BS_IV_DEFAULT, MS_PER_YEAR, dateMs,
  type Leg, multiLegPayoffPS, multiLegPayoffBSPS,
} from "@/lib/black-scholes";
import {
  type MultiLegType, type MultiLegStats, MULTI_LEG_META, PayoffYTick,
} from "./shared";

export default function MultiLegStrategyCard({
  strategy,
  data,
}: {
  strategy: MultiLegType;
  data: StrategyData;
}) {
  const meta = MULTI_LEG_META[strategy];
  const cp = data.current_price ?? 0;

  const callStrikes = useMemo<StrikeData[]>(
    () => data.strikes.filter((s) => s.call_mid != null).sort((a, b) => a.strike - b.strike),
    [data.strikes],
  );
  const putStrikes = useMemo<StrikeData[]>(
    () => data.strikes.filter((s) => s.put_mid != null).sort((a, b) => a.strike - b.strike),
    [data.strikes],
  );

  const irLo = data.implied_range_low;
  const irHi = data.implied_range_high;

  // Default short call: nearest call >= irHi, or ATM
  const defaultSC = useMemo(() => {
    if (irHi != null) {
      const found = callStrikes.find((s) => s.strike >= irHi);
      if (found) return found.strike;
    }
    return (
      callStrikes.find((s) => s.is_atm)?.strike ??
      callStrikes[Math.floor(callStrikes.length / 2)]?.strike ??
      0
    );
  }, [callStrikes, irHi]);

  // Default short put: nearest put <= irLo, or ATM
  const defaultSP = useMemo(() => {
    if (irLo != null) {
      const found = [...putStrikes].reverse().find((s) => s.strike <= irLo);
      if (found) return found.strike;
    }
    return (
      putStrikes.find((s) => s.is_atm)?.strike ??
      putStrikes[Math.floor(putStrikes.length / 2)]?.strike ??
      0
    );
  }, [putStrikes, irLo]);

  const [shortCallStrike, setShortCallStrike] = useState<number>(defaultSC);
  const [shortPutStrike, setShortPutStrike] = useState<number>(defaultSP);
  const [contracts, setContracts] = useState<number>(1);
  const [dateOffset, setDateOffset] = useState<number>(0);
  const [scrubPrice, setScrubPrice] = useState<number>(cp);

  useEffect(() => { setShortCallStrike(defaultSC); }, [defaultSC]);
  useEffect(() => { setShortPutStrike(defaultSP); }, [defaultSP]);

  const mult = contracts * 100;

  const T_today = data.expiration
    ? Math.max(0, (dateMs(data.expiration) - Date.now()) / MS_PER_YEAR)
    : 0;
  const T_earnings = (data.earnings_date && data.expiration)
    ? Math.max(0, (dateMs(data.expiration) - dateMs(data.earnings_date)) / MS_PER_YEAR)
    : null;
  const showEarnings = T_earnings !== null && T_earnings > 0 && T_earnings < T_today;

  // Date slider derived values
  const totalDays = Math.max(1, Math.round(T_today * 365.25));
  const T_slider = Math.max(0, (totalDays - dateOffset) / 365.25);
  const selectedDateMs = Date.now() + dateOffset * 86400000;
  const selectedDateStr = new Date(selectedDateMs).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const daysToExpiry = Math.max(0, totalDays - dateOffset);
  const earningsDateMs = data.earnings_date ? dateMs(data.earnings_date) : null;
  const showDisclaimer = showEarnings && earningsDateMs != null && selectedDateMs <= earningsDateMs;

  const { legs, stats } = useMemo<{ legs: Leg[]; stats: MultiLegStats }>(() => {
    const scObj = callStrikes.find((s) => s.strike === shortCallStrike);
    const spObj = putStrikes.find((s) => s.strike === shortPutStrike);
    // Wings: snap to the valid strike nearest to ±$10 from the short strike.
    // Dollar-width targeting is robust to missing strikes; index-stepping is not.
    const TARGET_WING = 10;

    const lcObj = scObj
      ? callStrikes
          .filter((s) => s.strike > shortCallStrike)
          .reduce<StrikeData | null>(
            (best, s) =>
              !best ||
              Math.abs(s.strike - (shortCallStrike + TARGET_WING)) <
                Math.abs(best.strike - (shortCallStrike + TARGET_WING))
                ? s
                : best,
            null,
          )
      : null;

    const lpObj = spObj
      ? putStrikes
          .filter((s) => s.strike < shortPutStrike)
          .reduce<StrikeData | null>(
            (best, s) =>
              !best ||
              Math.abs(s.strike - (shortPutStrike - TARGET_WING)) <
                Math.abs(best.strike - (shortPutStrike - TARGET_WING))
                ? s
                : best,
            null,
          )
      : null;

    // IV fallbacks: per-strike IV, then ATM IV, then global default
    const atmSd = data.strikes.find((s) => s.is_atm);
    const fbC = atmSd?.call_iv ?? BS_IV_DEFAULT;
    const fbP = atmSd?.put_iv  ?? BS_IV_DEFAULT;

    let legs: Leg[] = [];
    let netCredit = 0;
    let maxGain = 0;
    let maxLoss: number | null = 0;
    let breakevens: number[] = [];

    if (strategy === "bear_call_spread" && scObj && lcObj) {
      netCredit = scObj.call_mid! - lcObj.call_mid!;
      legs = [
        { kind: "call", K: scObj.strike, mid: scObj.call_mid!, sigma: scObj.call_iv ?? fbC, dir: -1, label: `Short call $${scObj.strike.toFixed(0)}` },
        { kind: "call", K: lcObj.strike, mid: lcObj.call_mid!, sigma: lcObj.call_iv ?? fbC, dir: 1,  label: `Long call $${lcObj.strike.toFixed(0)} (wing)` },
      ];
      maxGain = netCredit;
      maxLoss = lcObj.strike - scObj.strike - netCredit;
      breakevens = [scObj.strike + netCredit];
    } else if (strategy === "short_strangle" && scObj && spObj) {
      netCredit = scObj.call_mid! + spObj.put_mid!;
      legs = [
        { kind: "call", K: scObj.strike, mid: scObj.call_mid!, sigma: scObj.call_iv ?? fbC, dir: -1, label: `Short call $${scObj.strike.toFixed(0)}` },
        { kind: "put",  K: spObj.strike, mid: spObj.put_mid!,  sigma: spObj.put_iv  ?? fbP, dir: -1, label: `Short put $${spObj.strike.toFixed(0)}` },
      ];
      maxGain = netCredit;
      maxLoss = null;
      breakevens = [spObj.strike - netCredit, scObj.strike + netCredit];
    } else if (strategy === "iron_condor" && scObj && lcObj && spObj && lpObj) {
      netCredit = scObj.call_mid! + spObj.put_mid! - lcObj.call_mid! - lpObj.put_mid!;
      legs = [
        { kind: "call", K: scObj.strike, mid: scObj.call_mid!, sigma: scObj.call_iv ?? fbC, dir: -1, label: `Short call $${scObj.strike.toFixed(0)}` },
        { kind: "call", K: lcObj.strike, mid: lcObj.call_mid!, sigma: lcObj.call_iv ?? fbC, dir: 1,  label: `Long call $${lcObj.strike.toFixed(0)} (wing)` },
        { kind: "put",  K: spObj.strike, mid: spObj.put_mid!,  sigma: spObj.put_iv  ?? fbP, dir: -1, label: `Short put $${spObj.strike.toFixed(0)}` },
        { kind: "put",  K: lpObj.strike, mid: lpObj.put_mid!,  sigma: lpObj.put_iv  ?? fbP, dir: 1,  label: `Long put $${lpObj.strike.toFixed(0)} (wing)` },
      ];
      maxGain = netCredit;
      const callWingWidth = lcObj.strike - scObj.strike;
      const putWingWidth = spObj.strike - lpObj.strike;
      maxLoss = Math.max(callWingWidth, putWingWidth) - netCredit;
      breakevens = [spObj.strike - netCredit, scObj.strike + netCredit];
    }

    return { legs, stats: { netCredit, maxGain, maxLoss, breakevens } };
  }, [strategy, shortCallStrike, shortPutStrike, callStrikes, putStrikes]);

  // x-range: implied range ±30%, extended to include all strikes and breakevens
  const xRange = useMemo(() => {
    let lo: number, hi: number;
    if (irLo != null && irHi != null) {
      const pad = (irHi - irLo) * 0.30;
      lo = irLo - pad;
      hi = irHi + pad;
    } else {
      lo = cp * 0.80;
      hi = cp * 1.20;
    }
    for (const leg of legs) {
      if (leg.K < lo) lo = leg.K - (hi - lo) * 0.05;
      if (leg.K > hi) hi = leg.K + (hi - lo) * 0.05;
    }
    for (const be of stats.breakevens) {
      if (be < lo) lo = be - (hi - lo) * 0.05;
      if (be > hi) hi = be + (hi - lo) * 0.05;
    }
    return { lo, hi };
  }, [irLo, irHi, cp, legs, stats.breakevens]);

  // Live chartData: single pnl series, recomputes with each slider tick
  const chartData = useMemo(() => {
    if (!cp || !legs.length) return [];
    const { lo, hi } = xRange;
    return Array.from({ length: 100 }, (_, i) => {
      const S = lo + (i / 99) * (hi - lo);
      const pnl = T_slider > 0
        ? multiLegPayoffBSPS(legs, S, T_slider, BS_R) * mult
        : multiLegPayoffPS(legs, S) * mult;
      return { price: parseFloat(S.toFixed(2)), pnl: parseFloat(pnl.toFixed(2)) };
    });
  }, [legs, cp, mult, xRange, T_slider]);

  if (!callStrikes.length || !cp) {
    return (
      <div className="rounded-lg border bg-card px-5 py-4 text-sm text-muted-foreground">
        No valid contracts available for {meta.name}.
      </div>
    );
  }

  // Stable Y-axis: computed from expiry+today only so axis stays fixed as slider moves
  const yDomain = useMemo<[number, number]>(() => {
    if (!cp || !legs.length) return [-100, 100];
    const { lo, hi } = xRange;
    const vals: number[] = [];
    for (let i = 0; i < 100; i++) {
      const S = lo + (i / 99) * (hi - lo);
      vals.push(multiLegPayoffPS(legs, S) * mult);
      if (T_today > 0) vals.push(multiLegPayoffBSPS(legs, S, T_today, BS_R) * mult);
    }
    const yMin = Math.min(...vals);
    const yMax = Math.max(...vals);
    const pad = (yMax - yMin) * 0.15 || 1;
    return [yMin - pad, yMax + pad];
  }, [legs, cp, mult, xRange, T_today]);

  const xLo = chartData[0]?.price ?? 0;
  const xHi = chartData[chartData.length - 1]?.price ?? 0;
  const hasShortPut = strategy === "short_strangle" || strategy === "iron_condor";
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

      {/* Strike selectors */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground shrink-0">Short call:</span>
          <select
            value={shortCallStrike}
            onChange={(e) => setShortCallStrike(parseFloat(e.target.value))}
            className="rounded-md border bg-background px-2 py-1 text-sm"
          >
            {callStrikes.map((s) => (
              <option key={s.strike} value={s.strike}>
                ${s.strike.toFixed(0)}{s.is_atm ? " (ATM)" : ""} — call ${s.call_mid?.toFixed(2) ?? "\u2014"}
              </option>
            ))}
          </select>
        </div>
        {hasShortPut && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground shrink-0">Short put:</span>
            <select
              value={shortPutStrike}
              onChange={(e) => setShortPutStrike(parseFloat(e.target.value))}
              className="rounded-md border bg-background px-2 py-1 text-sm"
            >
              {putStrikes.map((s) => (
                <option key={s.strike} value={s.strike}>
                  ${s.strike.toFixed(0)}{s.is_atm ? " (ATM)" : ""} — put ${s.put_mid?.toFixed(2) ?? "\u2014"}
                </option>
              ))}
            </select>
          </div>
        )}
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

      {/* Legs summary */}
      {legs.length > 0 && (
        <div className="rounded-md bg-muted/40 px-3 py-2 text-xs space-y-0.5">
          {legs.map((leg, i) => (
            <div key={i} className="flex justify-between text-muted-foreground">
              <span>{leg.label}</span>
              <span className="tabular-nums">${leg.mid.toFixed(2)} mid</span>
            </div>
          ))}
        </div>
      )}

      {/* ── Hero P&L ──────────────────────────────────────────────── */}
      <div className="py-1">
        <p className="text-xs text-muted-foreground mb-1.5">
          {data.symbol} at ${effectivePrice.toFixed(2)}
          {" \u00b7 "}
          {daysToExpiry === 0 ? "At expiration" : selectedDateStr}
        </p>
        <p
          className={cn(
            "text-4xl font-bold tabular-nums tracking-tight leading-none",
            scrubPnl == null
              ? "text-muted-foreground"
              : scrubPnl >= 0
                ? "text-success"
                : "text-destructive",
          )}
        >
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
          <CartesianGrid strokeDasharray="2 6" stroke="hsl(var(--border))" strokeOpacity={0.4} vertical={false} />
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

          {/* Implied range band */}
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

          {/* Breakevens */}
          {stats.breakevens.map((be, i) => (
            <ReferenceLine
              key={i}
              x={be}
              stroke="hsl(var(--success))"
              strokeWidth={1}
              strokeDasharray="3 5"
              label={{ value: "B/E", position: "insideTopRight", fontSize: 9, fill: "hsl(var(--success))" }}
            />
          ))}

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
          It does not model the IV crush that typically follows an earnings release — real
          post-earnings option values will likely be lower.
        </Callout>
      )}

      {/* Key stats */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm pt-1 border-t">
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">Net credit:</span>
          <span className="font-medium tabular-nums text-green-600 dark:text-green-400">
            +${(stats.netCredit * mult).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>
        {stats.breakevens.map((be, i) => (
          <div key={i} className="flex justify-between gap-2">
            <span className="text-muted-foreground">
              Breakeven{stats.breakevens.length > 1 ? (be < cp ? " (down)" : " (up)") : " (stock price)"}:
            </span>
            <span className="font-medium tabular-nums">${be.toFixed(2)}</span>
          </div>
        ))}
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">Max gain:</span>
          <span className="font-medium tabular-nums text-green-600 dark:text-green-400">
            +${(stats.maxGain * mult).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">Max loss:</span>
          <span className="font-medium tabular-nums text-red-600 dark:text-red-400">
            {stats.maxLoss == null
              ? "Unlimited \u2193"
              : `\u2212$${(stats.maxLoss * mult).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          </span>
        </div>
      </div>
    </div>
  );
}
