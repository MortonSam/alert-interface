"use client";

import { useState } from "react";
import { type ExpectedMove, type OptionsChain } from "@/lib/api";
import Tip from "@/components/Tip";
import { fmtPctDecimal, TIPS } from "./shared";

export default function OptionsEducation({
  em,
  chain,
  symbol,
}: {
  em: ExpectedMove;
  chain: OptionsChain;
  symbol: string;
}) {
  const [open, setOpen] = useState(false);

  const atmCall   = chain.calls.find((c) => c.is_atm);
  const atmPut    = chain.puts.find((p)  => p.is_atm);
  const strike    = em.atm_strike;
  const price     = em.current_price;
  const emPct     = em.expected_move_pct;
  const exp       = em.expiration_used;

  const callMid = atmCall
    ? atmCall.bid != null && atmCall.ask != null
      ? (atmCall.bid + atmCall.ask) / 2
      : atmCall.last_price
    : null;
  const putMid = atmPut
    ? atmPut.bid != null && atmPut.ask != null
      ? (atmPut.bid + atmPut.ask) / 2
      : atmPut.last_price
    : null;

  const callBreakeven = strike != null && callMid != null ? strike + callMid : null;
  const putBreakeven  = strike != null && putMid  != null ? strike - putMid  : null;
  const callIV        = atmCall?.implied_volatility;

  return (
    <div className="mt-6 rounded-lg border bg-card overflow-visible">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-sm font-medium hover:bg-muted/30 transition-colors text-left"
        aria-expanded={open}
      >
        <span>How options work — applied to {symbol}</span>
        <span className="text-muted-foreground text-xs shrink-0 ml-4">{open ? "▲ Collapse" : "▼ Expand"}</span>
      </button>

      {open && (
        <div className="border-t divide-y divide-border/60">

          {/* 1 — Calls & Puts */}
          <section className="px-5 py-4 space-y-2 text-sm leading-relaxed">
            <h3 className="font-semibold">Calls & Puts</h3>
            <p className="text-muted-foreground">
              A <strong className="text-foreground">call option</strong> gives you the right to{" "}
              <em>buy</em> {symbol} at a fixed price (the <em>strike</em>) by the expiration date —
              no matter how high the stock goes.
              {strike != null && callMid != null && (
                <> The ${strike} call currently costs about{" "}
                  <strong className="text-foreground">${callMid.toFixed(2)}</strong> per share.
                  You profit if {symbol} climbs above{" "}
                  <strong className="text-foreground">
                    ${callBreakeven?.toFixed(2)}
                  </strong>{" "}
                  by {exp} — that's the strike plus the option's cost (your breakeven).
                </>
              )}
            </p>
            <p className="text-muted-foreground">
              A <strong className="text-foreground">put option</strong> is the mirror image — the
              right to <em>sell</em> at the strike, useful when you expect the stock to fall.
              {strike != null && putMid != null && (
                <> The ${strike} put costs about{" "}
                  <strong className="text-foreground">${putMid.toFixed(2)}</strong>.
                  It profits if {symbol} drops below{" "}
                  <strong className="text-foreground">
                    ${putBreakeven?.toFixed(2)}
                  </strong>{" "}
                  by {exp}.
                </>
              )}
            </p>
            <p className="text-muted-foreground">
              Options expire worthless if the stock never reaches the breakeven. You can also sell
              them before expiry — if the stock moves your way, the option gains value even before
              expiration.
            </p>
          </section>

          {/* 2 — Expected Move */}
          <section className="px-5 py-4 space-y-2 text-sm leading-relaxed">
            <h3 className="font-semibold">The Expected Move</h3>
            <p className="text-muted-foreground">
              The "expected move" comes from adding the ATM call and put prices together — a
              position called a <em>straddle</em>.
              {em.straddle_price != null && strike != null && (
                <> The ${strike} straddle costs{" "}
                  <strong className="text-foreground">${em.straddle_price.toFixed(2)}</strong>.
                  That's the market's implied range of motion in either direction.
                </>
              )}
            </p>
            {emPct != null && em.implied_range_low != null && em.implied_range_high != null && (
              <p className="text-muted-foreground">
                Dividing by the stock price gives{" "}
                <strong className="text-foreground">±{(emPct * 100).toFixed(1)}%</strong>, which
                puts the implied range at{" "}
                <strong className="text-foreground">
                  ${em.implied_range_low.toFixed(2)}–${em.implied_range_high.toFixed(2)}
                </strong>{" "}
                by {exp}. Any option struck <em>outside</em> that range is a bet that {symbol} moves
                more than the market currently expects.
              </p>
            )}
            {em.days_expiration_past_earnings != null && em.earnings_date && (
              <p className="text-muted-foreground text-xs italic">
                Note: the expiration is {em.days_expiration_past_earnings} days past the{" "}
                {em.earnings_date} earnings, so this range reflects the full period to expiration,
                not just the single earnings day.
              </p>
            )}
          </section>

          {/* 3 — Implied Volatility */}
          <section className="px-5 py-4 space-y-2 text-sm leading-relaxed">
            <h3 className="font-semibold">Implied Volatility (IV)</h3>
            <p className="text-muted-foreground">
              IV is the market's forecast of how much a stock will move, expressed as an annualized
              percentage. High IV = bigger expected swings = pricier options. Low IV = calmer
              expectations = cheaper options.
              {callIV != null && price != null && (
                <> {symbol}'s ATM call IV is currently{" "}
                  <strong className="text-foreground">{(callIV * 100).toFixed(1)}%</strong>{" "}
                  annualized.
                </>
              )}
            </p>
            {callIV != null && (
              <p className="text-muted-foreground">
                You can estimate the expected <em>daily</em> move by dividing by √252 (trading days
                per year): {(callIV * 100).toFixed(1)}% ÷ 15.9 ≈{" "}
                <strong className="text-foreground">
                  {((callIV / Math.sqrt(252)) * 100).toFixed(1)}% per day
                </strong>
                . Whether that's high or low <em>for {symbol} specifically</em> is called IV Rank — a
                future feature.
              </p>
            )}
          </section>

          {/* 4 — Reading the Chain */}
          <section className="px-5 py-4 space-y-2 text-sm leading-relaxed">
            <h3 className="font-semibold">Reading the Chain</h3>
            <p className="text-muted-foreground">
              The options chain shows every available strike for a given expiration. Each row has a
              call on the left and a put on the right, with the strike price in the middle. The{" "}
              <strong className="text-foreground">ATM row</strong> (highlighted in blue) is where the
              expected move is anchored.
            </p>
            <p className="text-muted-foreground">
              <strong className="text-foreground">Bid/Ask:</strong> the prices market makers will
              buy/sell at — the fair value is usually the midpoint.{" "}
              <strong className="text-foreground">IV</strong> is color-coded: warmer (orange) means
              higher implied volatility, cooler (blue) means lower. Notice that put IV is often
              higher than call IV at the same strike — this is called <em>volatility skew</em>,
              reflecting the market's greater fear of sharp drops than sharp rallies.
            </p>
          </section>

        </div>
      )}
    </div>
  );
}
