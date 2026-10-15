"""Beat and miss without licensed estimates. The Intrinio plan carries no analyst estimates and the Finnhub and Yahoo estimates
(and the actuals that come with them) are for personal use only, so LICENSED_ESTIMATES (config, default false) decides what every
page may show:

  on   today's behaviour: the estimate, beat, miss, surprise size and beat rate
  off  none of them, and no actual from those providers either: each place that showed one compares the reported EPS from SEC
       filings with the same quarter a year earlier (services/eps_year_ago), e.g. "EPS $2.22, up 111.4% from $1.05 a year ago",
       and says plainly when no year-ago figure exists

The helpers here are the only switch; every reader asks `licensed()` and strips with the functions below, so a test can crawl
the API with the setting off and find no estimate-derived value.
"""
from __future__ import annotations

import re
from datetime import date

from app.config import settings
from app.services.eps_year_ago import NO_YEAR_AGO, eps_line, load_quarters, quarter_for_report, year_ago_pairs

# fields that carry a provider's estimate, actual, or anything computed from them
ESTIMATE_FIELDS = ("eps_estimate", "eps_actual", "revenue_estimate", "revenue_actual", "eps_surprise_pct", "eps_surprise_dollars",
                   "eps_surprise_display_pct", "eps_beat_pct", "revenue_beat_pct", "beat_count", "beat_rate", "beat_rate_pct",
                   "beat_but_dropped_count", "beat_but_dropped_rate_pct", "avg_1d_on_beat", "avg_1d_on_miss", "median_1d_on_beat",
                   "median_1d_on_miss", "miss_count", "meet_count", "latest_outcome", "beat_continuation_5d_pct", "beat_5d_sample",
                   "beat_avg_5d", "beat_continuation_rate_pct", "miss_avg_5d", "miss_continuation_rate_pct", "miss_5d_sample",
                   "beat_cont_pct", "miss_cont_pct", "beat_5d_sample", "miss_5d_sample", "quarters_with_data", "quarters_without_data",
                   "unknown_count", "priced_in", "basis_excluded_note", "outcome_reason", "beats", "bbd_count", "beat_drops",
                   "beat_continuation_5d_pct")
# words that name an estimate-based judgement in prose
ESTIMATE_WORDS = re.compile(r"\b(?:beat|beats|beaten|beating|miss|missed|misses|surprises?|estimates?|consensus|"
                            r"(?:topped|exceeded|fell short of|below|above|ahead of) (?:analyst |Street |the )?expectations)\b", re.I)


def licensed() -> bool:
    return bool(settings.licensed_estimates)


def strip_fields(d: dict) -> dict:
    """Pure: the dict with every ESTIMATE_FIELDS key set to None (kept, so a schema still validates)."""
    return {k: (None if k in ESTIMATE_FIELDS else v) for k, v in d.items()}


def withhold(model):
    """A pydantic read with every ESTIMATE_FIELDS attribute it has set to None and licensed_estimates false; returned for chaining."""
    for name in getattr(type(model), "model_fields", {}):
        if name in ESTIMATE_FIELDS:
            setattr(model, name, None)
    if "licensed_estimates" in getattr(type(model), "model_fields", {}):
        model.licensed_estimates = False
    return model


def mentions_estimates(text: str | None) -> bool:
    return bool(text) and bool(ESTIMATE_WORDS.search(text))


def year_ago_fields(pair: dict | None) -> dict:
    """Pure: the fields a reaction row or a report carries instead of an estimate."""
    if pair is None:
        return {"sec_eps": None, "sec_eps_period_end": None, "year_ago_eps": None, "year_ago_period_end": None,
                "eps_change_pct": None, "eps_line": None}
    return {"sec_eps": pair["eps"], "sec_eps_period_end": pair["period_end"].isoformat(), "year_ago_eps": pair["year_ago_eps"],
            "year_ago_period_end": pair["year_ago_end"].isoformat() if pair["year_ago_end"] else None,
            "eps_change_pct": pair["pct"], "eps_line": eps_line(pair)}


class YearAgo:
    """One ticker's SEC quarters, loaded once, answering per report day."""
    def __init__(self, pairs: list[dict]):
        self.pairs = pairs

    @classmethod
    async def load(cls, db, symbol: str) -> "YearAgo":
        return cls(year_ago_pairs(await load_quarters(db, symbol)))

    def for_report(self, report_day: date) -> dict:
        return year_ago_fields(quarter_for_report(self.pairs, report_day))


def filter_note(structured: dict | None, verification: dict | None) -> tuple[dict | None, dict | None]:
    """Pure: with the setting off, a stored research note without its estimate-based points and claims: points and Bottom Line
    sentences that name a beat, miss, estimate or surprise are dropped, the stats lose every estimate field, and the verification
    keeps only the claims that name none (its totals recounted by the caller)."""
    if structured:
        s = dict(structured)
        for sec in ("highlights", "watch", "risks"):
            s[sec] = [p for p in (s.get(sec) or []) if not mentions_estimates(f"{p.get('lead', '')} {p.get('detail', '')}")]
        bl = re.split(r"(?<=[.!?])\s+(?=[A-Z])", s.get("bottom_line") or "")
        s["bottom_line"] = " ".join(x for x in bl if x and not mentions_estimates(x))
        if isinstance(s.get("stats"), dict):
            s["stats"] = strip_fields(s["stats"])
        structured = s
    if verification and isinstance(verification.get("claims"), list):
        verification = {**verification, "claims": [c for c in verification["claims"] if isinstance(c, dict) and not any(
            mentions_estimates(c.get(k)) for k in ("claim", "reason", "evidence"))]}
    return structured, verification


def filter_text(text: str | None) -> str | None:
    """Pure: stored prose without its sentences that name a beat, miss, estimate or surprise (Ivy's reasoning, a thesis)."""
    if not text:
        return text
    kept = [x for x in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if not mentions_estimates(x)]
    return " ".join(kept)


def filter_receipt(receipt: dict | None) -> dict | None:
    """Pure: a stored pick receipt without its estimate-based keys (beat_rate) and with its reasoning filtered."""
    if not isinstance(receipt, dict):
        return receipt
    out = {k: v for k, v in receipt.items() if k not in ESTIMATE_FIELDS}
    if isinstance(out.get("reasoning"), str):
        out["reasoning"] = filter_text(out["reasoning"])
    return out


__all__ = ["filter_receipt", "filter_text", "ESTIMATE_FIELDS", "NO_YEAR_AGO", "YearAgo", "filter_note", "licensed", "mentions_estimates", "strip_fields", "year_ago_fields"]
