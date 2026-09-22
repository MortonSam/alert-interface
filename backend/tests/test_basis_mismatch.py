"""A row whose estimate matches GAAP while its actual does not is basis_mismatch and carries no outcome."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.validate_data import ERROR, PASS, check_basis_mismatch_has_no_outcome, check_outcome_matches_eps
from app.services.basis_exclusion import BASIS_UNCLEAR_REASON, apply_basis_exclusion, basis_mismatch_dates, excluded_note
from app.services.eps_basis import BASIS_MISMATCH_FRACTION, BASIS_MISMATCH_MIN_ESTIMATE, classify, quarter_facts

D = Decimal
PLD = quarter_facts({"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
    {"start": "2025-10-01", "end": "2025-12-31", "val": 0.69, "filed": "2026-02-13"},
]}}}}})


def test_estimate_matching_gaap_with_a_far_actual_is_basis_mismatch():
    # ABT-shaped: estimate 1.14 is the GAAP consensus (GAAP 1.14), actual 1.43 is adjusted
    ABT = quarter_facts({"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        {"start": "2022-04-01", "end": "2022-06-30", "val": 1.14, "filed": "2022-07-28"}]}}}}})
    c = classify(D("1.43"), D("1.14"), date(2022, 7, 20), ABT, [])
    assert c.actual.status == "unmatched" and c.estimate_status == "matched" and c.basis_mismatch is True


def test_not_mismatch_when_actual_is_gaap_or_estimate_is_not_or_gap_is_small():
    assert classify(D("0.69"), D("0.68"), date(2026, 1, 21), PLD, []).basis_mismatch is False   # actual GAAP
    assert classify(D("1.46"), D("1.45"), date(2026, 1, 21), PLD, []).basis_mismatch is False   # both FFO
    # estimate matches, actual 0.80 vs GAAP 0.69: gap 0.11 <= 20% of 0.68
    c = classify(D("0.80"), D("0.68"), date(2026, 1, 21), PLD, [])
    assert c.actual.status == "unmatched" and c.basis_mismatch is False
    assert classify(D("1.46"), None, date(2026, 1, 21), PLD, []).estimate_status is None
    assert classify(D("1.46"), D("0.68"), date(2026, 9, 1), PLD, []).basis_mismatch is False    # no fact
    assert BASIS_MISMATCH_FRACTION == 0.20


def test_cent_level_estimates_cannot_fire():
    # UDR 2024-07-30: estimate 0.09 = GAAP 0.08, actual 0.10: a coincidence at cent level
    UDR = quarter_facts({"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        {"start": "2024-04-01", "end": "2024-06-30", "val": 0.08, "filed": "2024-07-31"}]}}}}})
    c = classify(D("0.10"), D("0.09"), date(2024, 7, 30), UDR, [])
    assert c.estimate_status == "matched" and c.basis_mismatch is False
    assert BASIS_MISMATCH_MIN_ESTIMATE == 0.25


def test_split_factor_explaining_the_estimate_must_not_explain_the_actual():
    # ANET 2021-11-01: XBRL 0.70 pre-split; estimate 0.17 = 0.70 / 4 (matched by the 4:1); actual 0.19 ~ 0.70 / 4 too
    ANET = quarter_facts({"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        {"start": "2021-07-01", "end": "2021-09-30", "val": 2.80, "filed": "2021-11-02"}]}}}}})   # scaled x4 to clear the 0.25 floor
    cands = [(4.0, date(2024, 12, 4))]
    c = classify(D("0.76"), D("0.70"), date(2021, 11, 1), ANET, cands)
    assert c.estimate_status == "off_by_split" and c.estimate_split_factor == 4.0
    assert c.basis_mismatch is False          # 0.76 is within 20% x 0.70 of 2.80 / 4 = 0.70
    c = classify(D("1.20"), D("0.70"), date(2021, 11, 1), ANET, cands)
    assert c.basis_mismatch is True           # 1.20 is 0.50 from 0.70: the split explains the estimate, not the actual


def test_min_rows_per_ticker():
    from app.services.eps_basis import BASIS_MISMATCH_MIN_ROWS, apply_min_rows
    assert BASIS_MISMATCH_MIN_ROWS == 2
    assert apply_min_rows([False, True, False]) == [False, False, False]
    assert apply_min_rows([True, False, True]) == [True, False, True]
    assert apply_min_rows([]) == []


def test_excluded_note_wording():
    assert excluded_note(0) is None
    assert excluded_note(1) == f"1 quarter excluded: {BASIS_UNCLEAR_REASON}"
    assert excluded_note(3) == f"3 quarters excluded: {BASIS_UNCLEAR_REASON}"


class _Rollback(Exception):
    pass


@pytest.mark.asyncio
async def test_exclusion_clears_outcome_and_validate_agrees(capsys):
    async def body():
        async with ScriptSessionLocal() as s:
            async with s.begin():
                tid = await s.scalar(text("""INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at)
                    VALUES (gen_random_uuid(), 'ZZBASIS', 'Basis test', true, now(), now()) RETURNING id"""))
                await s.execute(text("""INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, eps_estimate, eps_actual, outcome, computation_version, created_at)
                    VALUES (gen_random_uuid(), :t, 'earnings', :d, 0.68, 1.46, 'beat', 3, now()),
                           (gen_random_uuid(), :t, 'earnings', :d2, 0.70, 0.75, 'unknown', 3, now())"""),
                    {"t": tid, "d": date(2026, 1, 21), "d2": date(2025, 10, 15)})
                await s.execute(text("""INSERT INTO eps_basis_checks (id, ticker_id, event_date, stored_actual, match_status, basis_mismatch, checked_at)
                    VALUES (gen_random_uuid(), :t, :d, 1.46, 'unmatched', true, now()),
                           (gen_random_uuid(), :t, :d2, 0.75, 'matched', false, now())"""),
                    {"t": tid, "d": date(2026, 1, 21), "d2": date(2025, 10, 15)})
                out = await check_basis_mismatch_has_no_outcome(s)
                assert out.level == ERROR and any("ZZBASIS 2026-01-21" in r for r in out.rows)

                cleared, restored = await apply_basis_exclusion(s)
                assert cleared >= 1 and restored >= 1
                rows = dict((await s.execute(text(
                    "SELECT event_date, outcome::text FROM historical_reactions WHERE ticker_id = :t"), {"t": tid})).all())
                assert rows[date(2026, 1, 21)] == "unknown"      # flagged: outcome absent
                assert rows[date(2025, 10, 15)] == "beat"        # not flagged: outcome re-derived from its values
                assert await basis_mismatch_dates(s, tid) == {date(2026, 1, 21)}

                # scoped to this ticker: the local database may hold other flagged rows awaiting a feature rebuild
                assert not any("ZZBASIS" in r for r in (await check_basis_mismatch_has_no_outcome(s)).rows)
                # the flagged row is 'unknown' with both values present: outcome_matches_eps must accept that
                assert not any("ZZBASIS" in r for r in (await check_outcome_matches_eps(s)).rows)
                raise _Rollback

    with pytest.raises(_Rollback):
        await body()
