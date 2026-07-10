"use client";

import { type ExpectedMove } from "@/lib/api";
import Callout from "@/components/Callout";
import Tip from "@/components/Tip";
import { fmtPctDecimal, TIPS } from "./shared";

export default function ExpectedMoveCard({ em, onSelectExpiration }: { em: ExpectedMove; onSelectExpiration?: (exp: string) => void }) {
  const emPct = em.expected_move_pct;
  const emDol = em.expected_move_dollars;
  const stats = em.historical_stats;
  const daysPast = em.days_expiration_past_earnings;

  const isIsolated = daysPast != null && daysPast <= 3;
  const windowsMismatched = em.earnings_date != null && daysPast != null && daysPast > 3;

  return (
    <div className="rounded-lg border bg-card px-5 py-4 space-y-4">
      {/* Headline */}
      <div>
        <div className="text-2xl font-bold tabular-nums">
          {emPct != null ? `±${fmtPctDecimal(emPct)}` : "—"}
          {emDol != null && (
            <span className="text-lg font-semibold text-muted-foreground ml-2">
              (${emDol.toFixed(2)})
            </span>
          )}
        </div>

        <p className="text-sm text-muted-foreground mt-0.5">
          {isIsolated
            ? <>Earnings-day implied move — expiration{" "}
                {em.expiration_used && (
                  <button
                    className="underline underline-offset-2 hover:text-foreground transition-colors"
                    onClick={() => onSelectExpiration?.(em.expiration_used!)}
                  >
                    {em.expiration_used}
                  </button>
                )}{" "}
                is {daysPast === 0 ? "same day as" : `${daysPast}d after`} the {em.earnings_date} earnings
              </>
            : em.earnings_date
              ? <>Implied move by{" "}
                  {em.expiration_used && (
                    <button
                      className="underline underline-offset-2 hover:text-foreground transition-colors"
                      onClick={() => onSelectExpiration?.(em.expiration_used!)}
                    >
                      {em.expiration_used}
                    </button>
                  )}
                </>
              : <>Market implied move by{" "}
                  {em.expiration_used && (
                    <button
                      className="underline underline-offset-2 hover:text-foreground transition-colors"
                      onClick={() => onSelectExpiration?.(em.expiration_used!)}
                    >
                      {em.expiration_used}
                    </button>
                  )}
                </>
          }
        </p>

        {windowsMismatched && (
          <Callout severity="info" compact className="mt-1.5">
            This covers the full period to expiration — <strong>{daysPast} days past the {em.earnings_date} earnings</strong>.
            It reflects total vol over that window, not just the earnings event.
          </Callout>
        )}
      </div>

      {/* Implied range */}
      {em.implied_range_low != null && em.implied_range_high != null && (
        <div className="flex items-center gap-3 text-sm">
          <Tip text={TIPS.impliedRange}>
            <span className="text-muted-foreground underline decoration-dotted underline-offset-2">
              Implied range
            </span>
          </Tip>
          <span className="font-semibold tabular-nums">
            ${em.implied_range_low.toFixed(2)}
            <span className="text-muted-foreground mx-2">–</span>
            ${em.implied_range_high.toFixed(2)}
          </span>
        </div>
      )}

      {/* ATM detail */}
      {(em.atm_strike != null || em.straddle_price != null) && (
        <p className="text-xs text-muted-foreground flex items-center gap-1 flex-wrap">
          {em.atm_strike != null && (
            <Tip text={TIPS.atm}>
              <span className="underline decoration-dotted underline-offset-2">
                ATM strike ${em.atm_strike}
              </span>
            </Tip>
          )}
          {em.atm_strike != null && em.straddle_price != null && <span>·</span>}
          {em.straddle_price != null && (
            <Tip text={TIPS.straddle}>
              <span className="underline decoration-dotted underline-offset-2">
                straddle ${em.straddle_price.toFixed(2)}
              </span>
            </Tip>
          )}
        </p>
      )}

      {/* Historical 1-day earnings moves */}
      {stats && stats.sample_size >= 2 && (
        <div className="rounded-md border bg-muted/30 px-4 py-3 space-y-2">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Past earnings-day 1d moves (n={stats.sample_size})
          </p>
          <div className="grid grid-cols-3 gap-3 text-center">
            <div>
              <p className="text-xs text-muted-foreground">Avg</p>
              <p className="text-sm font-semibold tabular-nums">±{fmtPctDecimal(stats.avg_abs_move_pct)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Max</p>
              <p className="text-sm font-semibold tabular-nums">±{fmtPctDecimal(stats.max_abs_move_pct)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Min</p>
              <p className="text-sm font-semibold tabular-nums">±{fmtPctDecimal(stats.min_abs_move_pct)}</p>
            </div>
          </div>

          {isIsolated ? (
            <p className="text-xs text-muted-foreground">
              {stats.above_expected} of {stats.sample_size} past earnings exceeded this implied move ·{" "}
              historical avg ±{fmtPctDecimal(stats.avg_abs_move_pct)}
            </p>
          ) : (
            <p className="text-xs text-muted-foreground italic">
              Direct comparison unavailable — the implied ±{fmtPctDecimal(emPct)} covers{" "}
              {daysPast != null ? `${daysPast} days past earnings` : "multiple weeks"}, while these
              figures measure the single earnings day only.
            </p>
          )}
        </div>
      )}

      {em.data_quality_note && !windowsMismatched && (
        <p className="text-xs text-muted-foreground italic">{em.data_quality_note}</p>
      )}
    </div>
  );
}
