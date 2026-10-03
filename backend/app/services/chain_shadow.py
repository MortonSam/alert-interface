"""The Intrinio EOD chain beside the courier's: when it runs, what is stored, how the two compare, when it may retire the courier.

Schedule. The nightly step runs at SCHEDULED_LOCAL on the SCHEDULE_CLOCK, never at a UTC time: the market's day
ends on the New York clock, and a UTC cron drifts an hour against it twice a year. wait_seconds() says how long
the step waits when the pipeline reaches it early; the step outcome names the clock it ran on.

Storage. to_stored_chain() puts Intrinio's contracts in the courier's shape (strike, bid, ask, lastPrice, volume,
openInterest, impliedVolatility) with the quote timestamps kept, chain_last_trade set to the EOD date, and
chain_source "intrinio". The spot is the stored shadow bar's close for that date, never a live quote.

Comparison. compare_front() takes the two chains for the same ticker, date and front expiry: strikes on one
side only, the median and mean absolute mid difference over shared contracts, the implied move from each chain
the way services/implied_move computes it, the ATM mids at the courier chain's spot, and the courier's capture
time (chain_captured_at). The implied-move criterion is judged only for tickers the courier captured at or
after COURIER_CLOSE on the New York clock; an intraday capture against an EOD chain is "intraday, not judged".
evaluate() judges the stored nights: WARN until MIN_NIGHTS exist, then ERROR unless every one of the last
MIN_NIGHTS passes the retirement criteria.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.implied_move import mid_or_last, straddle_implied_move

SCHEDULED_LOCAL = time(3, 5)
SCHEDULE_CLOCK = "America/New_York"
MAX_WAIT_SECONDS = 3 * 3600          # a pipeline that reaches the step earlier than this is not the configured nightly: run, say so
MARKET_CLOSE_SETTLED = time(16, 15)  # after this local time a session's EOD chain may exist

MIN_NIGHTS = 7
IMPLIED_MOVE_TOLERANCE_PP = 0.3      # |Intrinio - courier| implied move, percentage points
IMPLIED_MOVE_SHARE = 0.95            # share of judged tickers whose implied moves agree within the tolerance
COURIER_CLOSE = time(16, 0)          # a courier capture at or after this New York time is a closing chain; earlier is intraday, not judged
INTRADAY_NOTE = "intraday, not judged"

PER_TICKER_COLUMNS = ["expiration", "courier_only_strikes", "intrinio_only_strikes", "shared_contracts", "mid_median", "mid_mean_abs",
                      "implied_move_courier_pct", "implied_move_intrinio_pct", "atm_strike", "atm_call_mid_courier", "atm_put_mid_courier",
                      "atm_call_mid_intrinio", "atm_put_mid_intrinio", "late", "chain_captured_at", "courier_after_close"]


# ── schedule ──────────────────────────────────────────────────────────────────

def local_now(now_utc: datetime | None = None) -> datetime:
    return (now_utc or datetime.now(ZoneInfo("UTC"))).astimezone(ZoneInfo(SCHEDULE_CLOCK))


def wait_seconds(now_utc: datetime) -> float:
    """Seconds until SCHEDULED_LOCAL on the schedule clock today; 0 when it has passed."""
    now = local_now(now_utc)
    target = now.replace(hour=SCHEDULED_LOCAL.hour, minute=SCHEDULED_LOCAL.minute, second=0, microsecond=0)
    return max(0.0, (target - now).total_seconds())


def clock_fields(now_utc: datetime, waited: float, ran_early_reason: str | None = None) -> dict:
    """What the step outcome says about when it ran: the clock, the schedule, the local time and its UTC offset."""
    now = local_now(now_utc)
    return {"clock": SCHEDULE_CLOCK, "scheduled_local": SCHEDULED_LOCAL.strftime("%H:%M"), "started_local": now.isoformat(),
            "utc_offset": now.strftime("%z")[:3] + ":" + now.strftime("%z")[3:], "tzname": now.tzname(),
            "waited_seconds": round(waited), **({"ran_early_reason": ran_early_reason} if ran_early_reason else {})}


def expected_session(now_local: datetime) -> date:
    """The session whose EOD chain should exist at this local time: today after the close on a trading day, else the last session before today."""
    from app.services.trading_calendar import is_trading_day, last_session_before
    d = now_local.date()
    if is_trading_day(d) and now_local.time() >= MARKET_CLOSE_SETTLED:
        return d
    return last_session_before(d)


# ── storage ───────────────────────────────────────────────────────────────────

def _contract(c: dict) -> dict:
    o, p = c.get("option") or {}, c.get("prices") or {}
    return {"strike": o.get("strike"), "bid": p.get("close_bid"), "ask": p.get("close_ask"), "lastPrice": p.get("close"), "mark": p.get("mark"),
            "volume": p.get("volume"), "openInterest": p.get("open_interest"), "impliedVolatility": p.get("implied_volatility"), "delta": p.get("delta"),
            "bid_time": p.get("close_bid_time"), "ask_time": p.get("close_ask_time"), "last_time": p.get("close_time"), "date": p.get("date")}


def chain_dates(contracts: list[dict]) -> list[str]:
    return sorted({(c.get("prices") or {}).get("date") for c in contracts if (c.get("prices") or {}).get("date")})


def to_stored_chain(contracts: list[dict], expiration: str, eod_date: date, spot: float | None, spot_source: str | None,
                    record: dict, fetched_at: datetime, expected: date) -> dict:
    """Intrinio's chain for one expiration in the courier's shape, with the quote timestamps kept."""
    calls = sorted((_contract(c) for c in contracts if (c.get("option") or {}).get("type") == "call"), key=lambda x: x["strike"] or 0)
    puts = sorted((_contract(c) for c in contracts if (c.get("option") or {}).get("type") == "put"), key=lambda x: x["strike"] or 0)
    stamps = [x[k] for x in calls + puts for k in ("bid_time", "ask_time", "last_time") if x.get(k)]
    return {"calls": calls, "puts": puts, "expiration": expiration, "chain_last_trade": eod_date.isoformat(),
            "underlying_price": spot, "underlying_price_source": spot_source, "chain_source": "intrinio",
            "security_record_id": record.get("id"), "intrinio_security_id": record.get("intrinio_security_id"), "intrinio_ticker": record.get("intrinio_ticker"),
            "quote_times": {"earliest": min(stamps) if stamps else None, "latest": max(stamps) if stamps else None},
            "expected_session": expected.isoformat(), "late": eod_date < expected, "fetched_at": fetched_at.isoformat()}


# ── comparison ────────────────────────────────────────────────────────────────

def captured_after_close(chain_captured_at: str | None) -> bool | None:
    """Whether the courier captured at or after COURIER_CLOSE on the New York clock. None when the chain has no stamp."""
    if not chain_captured_at:
        return None
    try:
        stamp = datetime.fromisoformat(chain_captured_at)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ZoneInfo(SCHEDULE_CLOCK))
    return stamp.astimezone(ZoneInfo(SCHEDULE_CLOCK)).time() >= COURIER_CLOSE


def front_expiration(expirations: list[str], chain_date: str) -> str | None:
    later = sorted(e for e in expirations if e > chain_date)
    return later[0] if later else None


def _mids(side: list[dict]) -> dict[float, float]:
    out = {}
    for c in side:
        k, m = c.get("strike"), mid_or_last(c.get("bid"), c.get("ask"), c.get("lastPrice"))
        if k is not None and m is not None:
            out[float(k)] = m
    return out


def _strikes(chain: dict) -> set[float]:
    return {float(c["strike"]) for side in ("calls", "puts") for c in chain.get(side, []) if c.get("strike") is not None}


def compare_front(courier: dict, intrinio: dict) -> dict:
    """Figures for one ticker's front expiry, both chains dated the same day. Keys follow PER_TICKER_COLUMNS."""
    sc, si = _strikes(courier), _strikes(intrinio)
    diffs: list[float] = []
    for side in ("calls", "puts"):
        mc, mi = _mids(courier.get(side, [])), _mids(intrinio.get(side, []))
        diffs += [mi[k] - mc[k] for k in mc.keys() & mi.keys()]
    imc = straddle_implied_move(courier.get("calls", []), courier.get("puts", []), courier.get("underlying_price"))
    imi = straddle_implied_move(intrinio.get("calls", []), intrinio.get("puts", []), intrinio.get("underlying_price"))
    spot = courier.get("underlying_price")
    both = {float(c["strike"]) for c in courier.get("calls", []) if c.get("strike") is not None} & \
           {float(p["strike"]) for p in courier.get("puts", []) if p.get("strike") is not None}
    atm = min(both, key=lambda s: abs(s - spot)) if spot and both else None
    cc, cp = _mids(courier.get("calls", [])), _mids(courier.get("puts", []))
    ic, ip = _mids(intrinio.get("calls", [])), _mids(intrinio.get("puts", []))
    r4 = lambda v: None if v is None else round(v, 4)
    return {
        "expiration": courier.get("expiration"),
        "courier_only_strikes": sorted(sc - si), "intrinio_only_strikes": len(si - sc), "shared_contracts": len(diffs),
        "mid_median": r4(statistics.median(diffs)) if diffs else None, "mid_mean_abs": r4(statistics.mean(abs(d) for d in diffs)) if diffs else None,
        "implied_move_courier_pct": r4(imc.pct * 100) if imc else None, "implied_move_intrinio_pct": r4(imi.pct * 100) if imi else None,
        "atm_strike": atm, "atm_call_mid_courier": r4(cc.get(atm)) if atm else None, "atm_put_mid_courier": r4(cp.get(atm)) if atm else None,
        "atm_call_mid_intrinio": r4(ic.get(atm)) if atm else None, "atm_put_mid_intrinio": r4(ip.get(atm)) if atm else None,
        "late": bool(intrinio.get("late")),
        "chain_captured_at": courier.get("chain_captured_at"), "courier_after_close": captured_after_close(courier.get("chain_captured_at")),
    }


def implied_moves_agree(fig: dict) -> bool:
    a, b = fig.get("implied_move_courier_pct"), fig.get("implied_move_intrinio_pct")
    return a is not None and b is not None and abs(a - b) <= IMPLIED_MOVE_TOLERANCE_PP


def night_totals(chain_date: str, per_ticker: dict[str, dict], missing_intrinio: list[str]) -> dict:
    """The night's totals from its per-ticker figures. `missing_intrinio`: tickers with a courier chain that night and no Intrinio chain."""
    n = len(per_ticker)
    judged = {s: f for s, f in per_ticker.items() if f.get("courier_after_close")}      # closing captures only
    agree = sum(1 for f in judged.values() if implied_moves_agree(f))
    medians = [f["mid_median"] for f in per_ticker.values() if f.get("mid_median") is not None]
    means = [f["mid_mean_abs"] for f in per_ticker.values() if f.get("mid_mean_abs") is not None]
    return {
        "date": chain_date, "tickers_both": n, "tickers_missing_intrinio": len(missing_intrinio), "missing_intrinio": sorted(missing_intrinio)[:50],
        "tickers_with_courier_only_strikes": sorted(s for s, f in per_ticker.items() if f["courier_only_strikes"])[:50],
        "courier_only_strikes": sum(len(f["courier_only_strikes"]) for f in per_ticker.values()),
        "intrinio_only_strikes": sum(f["intrinio_only_strikes"] for f in per_ticker.values()),
        "implied_move_judged": len(judged), "implied_move_intraday": n - len(judged),
        "implied_move_within_tolerance": agree, "implied_move_share": round(agree / len(judged), 4) if judged else None,
        "mid_median_of_medians": round(statistics.median(medians), 4) if medians else None,
        "mid_mean_abs_mean": round(statistics.mean(means), 4) if means else None,
        "late": sorted(s for s, f in per_ticker.items() if f.get("late"))[:50],
    }


@dataclass(frozen=True)
class Verdict:
    level: str          # "pass" | "warn" | "error"
    message: str
    rows: list[str]


def criteria_failures(t: dict) -> list[str]:
    """The retirement criteria a night fails, in words."""
    out = []
    if t.get("tickers_both", 0) == 0:
        return [f"{t.get('date')}: no ticker had both chains"]
    if t.get("courier_only_strikes", 0):
        out.append(f"{t['date']}: {t['courier_only_strikes']} courier strike(s) absent on the Intrinio side ({', '.join(t['tickers_with_courier_only_strikes'][:8])})")
    judged = t.get("implied_move_judged", 0)
    if judged and (t.get("implied_move_share") or 0) < IMPLIED_MOVE_SHARE:
        out.append(f"{t['date']}: implied moves within {IMPLIED_MOVE_TOLERANCE_PP} pp for {t.get('implied_move_within_tolerance', 0)}/{judged} closing-capture tickers "
                   f"({(t.get('implied_move_share') or 0) * 100:.1f}%), below {IMPLIED_MOVE_SHARE * 100:.0f}%")
    if t.get("tickers_missing_intrinio", 0):
        out.append(f"{t['date']}: {t['tickers_missing_intrinio']} ticker(s) with a courier chain and no Intrinio chain ({', '.join(t['missing_intrinio'][:8])})")
    if t.get("late"):
        out.append(f"{t['date']}: Intrinio published late for {len(t['late'])} ticker(s) ({', '.join(t['late'][:8])})")
    return out


def evaluate(nights: list[dict], min_nights: int = MIN_NIGHTS) -> Verdict:
    """`nights`: stored night totals, any order. WARN until min_nights exist; then ERROR unless the last min_nights all pass."""
    nights = sorted(nights, key=lambda t: t["date"])
    if not nights:
        return Verdict("warn", "No shadow night stored yet", [])
    latest = nights[-1]
    judged = latest.get("implied_move_judged", 0)
    im = (f"implied moves within {IMPLIED_MOVE_TOLERANCE_PP} pp for {latest['implied_move_within_tolerance']}/{judged} closing-capture tickers"
          + (f" ({latest.get('implied_move_intraday', 0)} {INTRADAY_NOTE})" if latest.get("implied_move_intraday") else "")) if judged else \
         f"implied moves: no courier capture at or after {COURIER_CLOSE.strftime('%H:%M')} New York (captured before it, or unstamped), {INTRADAY_NOTE}"
    rows = [f"{latest['date']}: {latest['tickers_both']} ticker(s) with both chains, {latest['tickers_missing_intrinio']} missing Intrinio, "
            f"courier-only strikes {latest['courier_only_strikes']}, {im}, mid median {latest['mid_median_of_medians']}, mean abs {latest['mid_mean_abs_mean']}, "
            f"late {len(latest['late'])}"]
    if len(nights) < min_nights:
        failures = criteria_failures(latest)
        return Verdict("warn", f"Shadow week in progress: {len(nights)} of {min_nights} nights stored" + ("; tonight fails " + str(len(failures)) + " criterion(s)" if failures else "; tonight passes"),
                       rows + failures)
    window = nights[-min_nights:]
    failures = [f for t in window for f in criteria_failures(t)]
    if failures:
        return Verdict("error", f"Retirement criteria fail in the last {min_nights} nights ({len(failures)} failure(s))", rows + failures)
    return Verdict("pass", f"Last {min_nights} nights pass the retirement criteria ({window[0]['date']}..{window[-1]['date']})", rows)
