"""The batch quote endpoints withhold a stale quote exactly as the single-quote endpoint does."""
from datetime import datetime, timedelta, timezone

from app.routers.tickers import _served_quote


def _ts(days_ago: int) -> int:
    return int((datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp())


def test_fresh_quote_is_served_whole():
    out = _served_quote({"price": 339.07, "change": 2.94, "change_pct": 0.87, "timestamp": _ts(0)})
    assert out["price"] == 339.07 and out["change_pct"] == 0.87
    assert out["quote_state"] == "ok" and out["quote_reason"] is None


def test_stale_quote_renders_absent_with_a_plain_reason():
    # EQR: Finnhub returned 65.35 with a last trade weeks old.
    out = _served_quote({"price": 65.35, "change": 0.39, "change_pct": 0.6, "timestamp": _ts(20)})
    assert out["price"] is None and out["change"] is None and out["change_pct"] is None
    assert out["quote_state"] == "stale"
    assert "no longer current" in out["quote_reason"]
    assert out["timestamp"] is not None          # the trade time itself is still reported


def test_missing_quote_and_missing_trade_time():
    assert _served_quote({})["quote_state"] == "no_data"
    assert _served_quote({"price": 10.0, "change": 0, "change_pct": 0})["price"] is None


def test_both_batch_endpoints_and_the_ledger_use_the_shared_test():
    from pathlib import Path
    app = Path(__file__).resolve().parents[1] / "app" / "routers"
    tickers = (app / "tickers.py").read_text()
    assert tickers.count("_served_quote(") >= 4          # definition + /quotes (hit, miss) + /batch-enrich
    assert "assess_quote(price_map.get(sym), ts_map.get(sym))" in (app / "thesis.py").read_text()
