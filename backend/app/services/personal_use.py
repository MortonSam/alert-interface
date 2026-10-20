"""Data whose source licence is personal use only (Block 2, 2026-10-20): Finnhub's free plan and Yahoo Finance may not be displayed
on a public site. PERSONAL_USE_DATA_SHOWN (config, default false) keeps every figure that rests on them off the pages until Sam's go:

  quotes            every visitor-priority Finnhub quote (finnhub_client.get_quote) is the stored Intrinio close instead
                    (quote_fallback), dated as a close; the live layer's delayed Intrinio quote (LIVE_DATA_ENABLED) is unaffected
  company news      the ticker page's news (Finnhub company news) and Discover's news and movers are withheld
  analyst data      analyst actions, their reaction statistics and recommendation trends (Finnhub, Yahoo) are withheld
  market value      the Finnhub market cap and shares outstanding: the header's market cap and the Overview's "worth about" clause
  report dates      a vendor's calendar date is never shown: the LICENSED_DATES_ONLY behaviour (company-confirmed dates, otherwise
                    an expected window from SEC filings)
  dividends         the forward ex-dividend date from Yahoo is withheld (past ex-dates come from the Intrinio bars)
  counters          the home page's analyst actions counter

licensed_sources.md (backend/ops/reports/block2_2026-10-20) lists every visible element, its source and plan, and what this does to it.
"""
from __future__ import annotations

from app.config import settings


def shown() -> bool:
    """Data from a personal-use source may be displayed (PERSONAL_USE_DATA_SHOWN, off by default)."""
    return bool(getattr(settings, "personal_use_data_shown", False))


def dates_licensed_only() -> bool:
    """A page shows only company-confirmed report dates (or an expected window): LICENSED_DATES_ONLY, or personal-use data held."""
    return bool(settings.licensed_dates_only) or not shown()


def withheld_event(event) -> bool:
    """Pure (given the flag): an event a visitor may not see while personal-use data is held: an analyst action (Finnhub, Yahoo
    upgrades and downgrades) or an ex-dividend date whose source is Yahoo (the forward date; past ex-dates come from Intrinio bars)."""
    if shown():
        return False
    kind = getattr(getattr(event, "event_type", None), "value", getattr(event, "event_type", None))
    source = getattr(getattr(event, "source", None), "value", getattr(event, "source", None))
    return kind == "analyst_action" or (kind == "ex_dividend" and source == "yfinance")
