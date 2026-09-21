"""Ivy's numbers reach pages only through ivy_rule() and the stored backtest."""
import re
from pathlib import Path

from app.constants import LEDGER_PUBLIC, LEDGER_START
from app.services import chain_store, ivy_v2
from app.services.ivy_backtest import summarize
from app.services.ivy_rule import ivy_rule

APP = Path(__file__).resolve().parents[1] / "app"


def test_rule_field_is_built_from_the_constants_the_code_applies():
    rule = ivy_rule()
    assert rule["momentum_cutoff_pct"] == ivy_v2.MOMENTUM_CUTOFF * 100
    assert rule["min_prior_quarters"] == ivy_v2.MIN_PRIOR_N
    assert rule["implied_move_multiple"] == ivy_v2.IV_PREMIUM_CAP
    assert rule["exit_trading_days"] == ivy_v2.EXIT_TRADING_DAYS
    assert rule["max_new_picks_per_night"] == ivy_v2.MAX_NEW_PER_NIGHT
    assert rule["max_open_picks"] == ivy_v2.MAX_OPEN_TOTAL
    assert rule["ledger_start"] == LEDGER_START.isoformat()
    assert rule["ledger_public"] is LEDGER_PUBLIC
    assert rule["chain_fresh_trading_days"] == chain_store.CHAIN_FRESH_TRADING_DAYS


def test_the_constants_are_used_where_the_behaviour_happens():
    auto_pick = (APP / "scripts" / "auto_pick.py").read_text()
    thesis = (APP / "routers" / "thesis.py").read_text()
    assert "nth_trading_day_after(event_date, EXIT_TRADING_DAYS)" in auto_pick
    assert "timedelta(days=CANDIDATE_WINDOW_DAYS)" in auto_pick
    assert not re.search(r"^MAX_(NEW_PER_NIGHT|OPEN_TOTAL)\s*=", auto_pick, re.M)   # defined once, in ivy_v2
    assert not re.search(r"nth_trading_day_after\([^)]*,\s*5\)", auto_pick + thesis)


def test_backtest_summary_pools_counts_and_keeps_precision():
    folds = [
        {"label": "2023", "setups": 47, "hits": 28, "base_n": 1960, "base_ups": 1010},
        {"label": "2024", "setups": 70, "hits": 38, "base_n": 1977, "base_ups": 1059},
        {"label": "2025-26", "setups": 248, "hits": 132, "base_n": 3481, "base_ups": 1816},
    ]
    out = summarize(folds)
    assert (out["setups"], out["hits"], out["base_n"]) == (365, 198, 7418)
    assert round(out["hit_rate"] * 100, 1) == 54.2            # 198/365, not the 54.3 a 4-decimal rate rounds to
    assert out["hit_rate"] == round(198 / 365, 6)
    assert out["base_rate"] == round((1010 + 1059 + 1816) / 7418, 6)   # pooled, not the mean of fold rates
    assert [f["label"] for f in out["folds"]] == ["2023", "2024", "2025-26"]


def test_empty_fold_does_not_divide_by_zero():
    out = summarize([{"label": "2030", "setups": 0, "hits": 0, "base_n": 0, "base_ups": 0}])
    assert out["folds"][0]["hit_rate"] is None and out["hit_rate"] == 0.0
