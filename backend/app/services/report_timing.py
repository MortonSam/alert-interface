"""The one rule that decides whether an earnings report was pre-market or after-close.

Two kinds of evidence, used differently:

  Acceptance time of the Item 2.02 8-K bounds the release: a report cannot be
  released after the filing that contains it. It is decisive when the filing is
  accepted before the open. A filing accepted after the close only says the
  release happened some time before it.

  Price confirms a ticker-level pattern. Opening gaps decide, per ticker, whether
  it habitually reports pre-market or after-close. Price never picks a single
  row's window: choosing the window with the larger move inflates average moves
  on quiet quarters.

Everything here is pure: no database, no network.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

TIMING_RULE_VERSION = 1

# Ticker pattern: share of price-decisive rows needed, and how many such rows.
PATTERN_THRESHOLD = 0.80
PATTERN_MIN_DECISIVE = 6

# Price signal: the larger opening gap must be this multiple of the smaller, and this big.
GAP_RATIO = 2.0
GAP_MIN_PCT = 1.0

# Tickers whose EDGAR acceptance stamp is Eastern clock time mislabeled as UTC.
# Evidence: the raw clock does not shift with daylight saving, and price agrees
# with the Eastern reading. Everything else is true UTC.
EASTERN_CLOCK_TICKERS: frozenset[str] = frozenset({"TTWO"})

EARNINGS_ITEM = "2.02"          # 8-K "Results of Operations and Financial Condition"
ITEM_202_WINDOW_DAYS = 3        # how far from event_date an Item 2.02 filing may sit

ET = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


# ── Filing selection ─────────────────────────────────────────────────────────

def has_earnings_item(items: str) -> bool:
    return EARNINGS_ITEM in [i.strip() for i in (items or "").split(",")]


def parse_acceptance(raw: str) -> datetime | None:
    """EDGAR acceptanceDateTime -> aware UTC datetime."""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None


@dataclass(frozen=True)
class Filing:
    filing_date: date
    acceptance: datetime     # aware UTC, as EDGAR labels it
    is_earnings_item: bool


def select_filing(filings: list[tuple[str, str, str]], event_date: date) -> Filing | None:
    """The 8-K that dates this report: the Item 2.02 filing nearest event_date.

    Ties go to the earliest acceptance. With no Item 2.02 filing within
    ITEM_202_WINDOW_DAYS, falls back to the first 8-K filed on event_date or
    the day after (flagged is_earnings_item=False).
    """
    parsed: list[Filing] = []
    for fd_str, at_str, items in filings:
        acc = parse_acceptance(at_str)
        try:
            fd = date.fromisoformat(fd_str)
        except (ValueError, TypeError):
            continue
        if acc is not None:
            parsed.append(Filing(fd, acc, has_earnings_item(items)))

    earnings = [f for f in parsed if f.is_earnings_item and abs((f.filing_date - event_date).days) <= ITEM_202_WINDOW_DAYS]
    if earnings:
        return min(earnings, key=lambda f: (abs((f.filing_date - event_date).days), f.acceptance))
    nearby = [f for f in parsed if f.filing_date in (event_date, event_date + timedelta(days=1))]
    return min(nearby, key=lambda f: f.acceptance) if nearby else None


# ── Acceptance bound ─────────────────────────────────────────────────────────

def acceptance_eastern(symbol: str, acceptance: datetime) -> datetime:
    """Naive Eastern clock time of an acceptance stamp, honouring EASTERN_CLOCK_TICKERS."""
    if symbol in EASTERN_CLOCK_TICKERS:
        return acceptance.replace(tzinfo=None)
    return acceptance.astimezone(ET).replace(tzinfo=None)


def acceptance_bucket(symbol: str, acceptance: datetime | None, event_date: date) -> str:
    """Where the filing sits relative to event day T.

    pre_open    before 09:30 on T, or at/after 16:00 on T-1
    intraday    09:30-16:00 on T
    post_close  at/after 16:00 on T, or before 09:30 on T+1
    far         any other day: the stored event date cannot be reconciled with it
    none        no filing
    """
    if acceptance is None:
        return "none"
    local = acceptance_eastern(symbol, acceptance)
    offset, clock = (local.date() - event_date).days, local.time()
    if offset == 0:
        return "pre_open" if clock < MARKET_OPEN else ("intraday" if clock < MARKET_CLOSE else "post_close")
    if offset == 1 and clock < MARKET_OPEN:
        return "post_close"
    if offset == -1 and clock >= MARKET_CLOSE:
        return "pre_open"
    return "far"


# ── Ticker pattern from price ────────────────────────────────────────────────

def _zero_volume(vol) -> bool:
    return vol == 0 or (isinstance(vol, float) and np.isnan(vol))


def _session_offset(sessions: np.ndarray, day: date, offset: int) -> date | None:
    pos = int(np.searchsorted(sessions, day))
    if pos >= len(sessions) or sessions[pos] != day:
        return None
    target = pos + offset
    return sessions[target] if 0 <= target < len(sessions) else None


def opening_gap(hist, dates: np.ndarray, sessions: np.ndarray, day: date) -> float | None:
    """|open(day) / close(prior session) - 1| in percent; None unless both bars exist and traded."""
    prior = _session_offset(sessions, day, -1)
    if prior is None:
        return None
    i, j = np.flatnonzero(dates == day), np.flatnonzero(dates == prior)
    if i.size == 0 or j.size == 0:
        return None
    if _zero_volume(hist["Volume"].iloc[int(i[0])]) or _zero_volume(hist["Volume"].iloc[int(j[0])]):
        return None
    base = float(hist["Close"].iloc[int(j[0])])
    return abs(float(hist["Open"].iloc[int(i[0])]) / base - 1) * 100 if base else None


def price_signal(
    hist, dates: np.ndarray, sessions: np.ndarray, filing_session: date, event_session: date,
) -> tuple[str, float | None, float | None]:
    """'bmo' | 'amc' | 'off' | 'none' relative to the stored event date, plus both gaps.

    Compares the opening gap on the filing day with the next session's. Counted
    only when the larger is GAP_RATIO times the smaller and at least GAP_MIN_PCT.
    """
    g_f = opening_gap(hist, dates, sessions, filing_session)
    nxt = _session_offset(sessions, filing_session, 1)
    g_n = opening_gap(hist, dates, sessions, nxt) if nxt is not None else None
    if g_f is None or g_n is None:
        return "none", g_f, g_n
    hi, lo = max(g_f, g_n), min(g_f, g_n)
    if hi < GAP_MIN_PCT or hi < GAP_RATIO * lo:
        return "none", g_f, g_n
    in_filing_day_open = g_f > g_n
    offset = int(np.searchsorted(sessions, filing_session) - np.searchsorted(sessions, event_session))
    if offset == 0:
        return ("bmo" if in_filing_day_open else "amc"), g_f, g_n
    if offset == 1 and in_filing_day_open:
        return "amc", g_f, g_n
    if offset == -1 and not in_filing_day_open:
        return "bmo", g_f, g_n
    return "off", g_f, g_n


@dataclass(frozen=True)
class Pattern:
    pattern: str          # "bmo" | "amc" | "mixed"
    decisive_rows: int
    bmo_share: float | None


def ticker_pattern(signals: list[str]) -> Pattern:
    """Ticker-level habit from its rows' price signals."""
    n_bmo, n_amc = signals.count("bmo"), signals.count("amc")
    n = n_bmo + n_amc
    if n == 0:
        return Pattern("mixed", 0, None)
    share = n_bmo / n
    if n >= PATTERN_MIN_DECISIVE and share >= PATTERN_THRESHOLD:
        return Pattern("bmo", n, share)
    if n >= PATTERN_MIN_DECISIVE and (1 - share) >= PATTERN_THRESHOLD:
        return Pattern("amc", n, share)
    return Pattern("mixed", n, share)


# ── The rule ─────────────────────────────────────────────────────────────────

_BUCKET_IMPLIES = {"pre_open": "bmo", "intraday": "bmo", "post_close": "amc"}

@dataclass(frozen=True)
class Decision:
    timing: str           # "bmo" | "amc" | "unknown"
    source: str           # short machine-readable reason, stored as timing_source
    explanation: str


def classify(
    symbol: str,
    event_date: date,
    filing: Filing | None,
    pattern: str,
    stored_timing: str = "unknown",
) -> Decision:
    """Decide one earnings row's timing. `pattern` is the ticker's Pattern.pattern."""
    bucket = acceptance_bucket(symbol, filing.acceptance if filing else None, event_date)

    if filing is not None and not filing.is_earnings_item:
        return _classify_borrowed(bucket, pattern)

    if bucket == "pre_open":
        return Decision("bmo", "accepted_pre_open", "filing accepted before the open bounds the release")
    if bucket == "intraday":
        if pattern == "amc":
            return Decision("unknown", "contradiction_intraday_vs_amc_pattern",
                            "filed intraday but the ticker's price pattern is after-close")
        return Decision("bmo", "accepted_intraday",
                        "released before an intraday filing: not after the close, and the move lands on T")
    if bucket == "post_close":
        if pattern == "bmo":
            return Decision("bmo", "accepted_post_close_pattern_bmo",
                            "filed after the close, but the ticker's price pattern is pre-market")
        return Decision("amc", "accepted_post_close", "filing accepted after the close")
    if bucket == "none":
        if pattern in ("bmo", "amc") and stored_timing == pattern:
            return Decision(pattern, "no_filing_stored_matches_pattern",
                            "no filing; the stored timing matches the ticker's price pattern")
        return Decision("unknown", "no_filing", "no 8-K found near the event date")
    return Decision("unknown", "filing_far_from_event_date",
                    "the nearest filing is on a day the stored event date cannot explain")


def _classify_borrowed(bucket: str, pattern: str) -> Decision:
    """A row with no Item 2.02 filing, leaning on another 8-K filed that day.

    That filing's acceptance time does not bound the earnings release, so it is
    only corroboration: a timing is assigned when it agrees with the ticker's
    price pattern, and the row is unknown otherwise.
    """
    implied = _BUCKET_IMPLIES.get(bucket)
    if implied is None:
        return Decision("unknown", "filing_far_from_event_date_any8k",
                        "no earnings filing; the nearest 8-K is on a day the stored event date cannot explain")
    if pattern == "mixed":
        return Decision("unknown", "any8k_pattern_mixed",
                        "no earnings filing, and the ticker has no clear price pattern to confirm another 8-K's time")
    if implied != pattern:
        return Decision("unknown", "any8k_disagrees_with_pattern",
                        f"no earnings filing; another 8-K suggests {implied} but the ticker's price pattern is {pattern}")
    return Decision(pattern, f"any8k_agrees_with_pattern_{pattern}",
                    f"no earnings filing; another 8-K and the ticker's price pattern both say {pattern}")
