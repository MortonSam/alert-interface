"""A NaN never reaches a JSONB column: the feature producer stores None with a reason, the writer refuses NaN."""
import json
import math
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal, strict_json_dumps
from app.models.alert_pick import AlertPick
from app.models.shadow_pick import ShadowPick
from app.services import ivy_v2
from app.services.ivy_shadow import _extract_row_from_dict
from app.services.ivy_v2 import LiveFeatures, compute_live_features


class _Rollback(Exception):
    pass


def _history(last_close):
    idx = pd.to_datetime(["2026-08-24", "2026-09-21", "2026-09-22"])
    return pd.DataFrame({"Close": [800.0, 890.0, last_close]}, index=idx)


@pytest.mark.asyncio
async def test_nan_close_gives_momentum_none_with_a_reason(monkeypatch):
    class FakeTicker:
        def __init__(self, sym): pass
        def history(self, period, timeout): return _history(float("nan"))
    monkeypatch.setattr(ivy_v2.yf, "Ticker", FakeTicker)
    async with ScriptSessionLocal() as s:
        lf = await compute_live_features("COST", s)
    assert lf is not None and lf.momentum_20d is None
    assert lf.momentum_reason == "price history has a non-finite close"

    class FiniteTicker(FakeTicker):
        def history(self, period, timeout): return _history(880.0)
    monkeypatch.setattr(ivy_v2.yf, "Ticker", FiniteTicker)
    async with ScriptSessionLocal() as s:
        lf = await compute_live_features("COST", s)
    assert lf.momentum_20d == 10.0 and lf.momentum_reason is None


def test_the_json_writer_refuses_nan_and_infinity():
    assert strict_json_dumps({"m": 1.5, "r": None}) == '{"m": 1.5, "r": null}'
    for bad in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(ValueError):
            strict_json_dumps({"momentum_20d": bad})
    assert json.dumps({"m": float("nan")}) == '{"m": NaN}'   # what Postgres rejected


@pytest.mark.asyncio
async def test_a_pick_receipt_built_from_nan_guarded_features_saves_and_a_raw_nan_is_refused():
    features = LiveFeatures(symbol="ZZNAN", event_date=date(2026, 9, 24), momentum_20d=None, prior_n=16,
                            prior_avg_abs_5d=3.6, prior_up_5d_rate=0.375, beat_rate=75.0,
                            momentum_reason="price history has a non-finite close")
    receipt = {"n_comparable": features.prior_n, "momentum_20d": features.momentum_20d,
               "momentum_reason": features.momentum_reason, "expected_pct": 3.6, "implied_pct": 4.1}
    async with ScriptSessionLocal() as s:
        with pytest.raises(_Rollback):
            async with s.begin():
                s.add(AlertPick(symbol="ZZNAN", picked_direction="bullish", algo_version="v2.0", leans=[],
                                strategy="bull call spread", expiration="2026-10-16", source="nightly", season=2,
                                receipt=receipt, exit_rule="5d_after_earnings", reasoning="test", entry_price=Decimal("900.00")))
                await s.flush()
                stored = (await s.execute(text("SELECT receipt FROM alert_picks WHERE symbol = 'ZZNAN'"))).scalar_one()
                assert stored["momentum_20d"] is None and stored["momentum_reason"] == "price history has a non-finite close"
                raise _Rollback
    async with ScriptSessionLocal() as s:
        with pytest.raises(Exception) as excinfo:
            async with s.begin():
                s.add(AlertPick(symbol="ZZNAN", picked_direction="bullish", algo_version="v2.0", leans=[],
                                source="nightly", season=2, receipt={"momentum_20d": float("nan")}, entry_price=Decimal("900.00")))
                await s.flush()
        assert "not JSON compliant" in str(excinfo.value)       # the writer, not Postgres, refuses it
    async with ScriptSessionLocal() as s:
        assert await s.scalar(text("SELECT count(*) FROM alert_picks WHERE symbol = 'ZZNAN'")) == 0


@pytest.mark.asyncio
async def test_shadow_imputes_a_nan_feature_and_its_upsert_saves():
    medians = {"momentum_20d": -1.5, "beat_rate": 70.0}
    row = _extract_row_from_dict({"momentum_20d": float("nan"), "beat_rate": 75.0}, medians, ["momentum_20d", "beat_rate"])
    assert row == [-1.5, 1.0, 75.0, 0.0]        # NaN imputed with the median and flagged null
    assert all(math.isfinite(v) for v in row)
    async with ScriptSessionLocal() as s:
        with pytest.raises(_Rollback):
            async with s.begin():
                s.add(ShadowPick(symbol="ZZNAN", event_date=date(2026, 9, 24), eval_date=date(2026, 9, 23),
                                 probability=Decimal("0.5720"), threshold_used=Decimal("0.55"), would_pick=False,
                                 top_factors=["prior event count 16 pushed down"], v2_decision="skipped"))
                await s.flush()
                assert await s.scalar(text("SELECT count(*) FROM shadow_picks WHERE symbol = 'ZZNAN'")) == 1
                raise _Rollback
