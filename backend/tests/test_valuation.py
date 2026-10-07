"""Trailing P/E from filings: the release parser on Micron's Sep 30, 2026 exhibit text, quarterly facts with the derived
fourth quarter, the freshness rule (the window must hold the latest reported quarter), the history summary with its
exclusions, the release-against-XBRL flag, and the checker's quarter match."""
from datetime import date

from app.scripts.check_release_eps import derived_only_match, matching_quarter
from app.scripts.seed_release_eps import exhibit_text
from app.services import valuation as V

MU_RELEASE = ("MICRON TECHNOLOGY, INC. REPORTS RESULTS FOR THE FOURTH QUARTER AND FULL YEAR OF FISCAL 2026. Fiscal Q4 2026 highlights • Revenue of $54.23 billion "
              "versus $41.46 billion for the prior quarter • GAAP net income of $37.70 billion, or $32.87 per diluted share • Non-GAAP net income of $38.40 billion, "
              "or $33.42 per diluted share • Fiscal 2026 Highlights • GAAP net income of $84.97 billion, or $74.33 per diluted share • Non-GAAP net income of $86.76 billion, "
              "or $75.52 per diluted share. 4th Qtr. 3rd Qtr. 4th Qtr. Year Ended September 3, 2026 May 28, 2026 August 28, 2025 "
              "GAAP diluted earnings per share $ 32.87 $ 24.67 $ 2.83 $ 74.33 $ 7.59 Non-GAAP diluted earnings per share $ 33.42 $ 25.11 $ 3.03")
TABLE_ONLY = ("Results for the quarter ended June 30, 2026. Non-GAAP diluted earnings per share $ 2.10 $ 1.90 "
              "Diluted earnings per share $ 1.84 $ 1.62 Weighted average shares 1,000")


def test_release_parser_reads_the_quarters_gaap_figure_not_the_years_or_the_non_gaap_one():
    hit = V.parse_release_eps(MU_RELEASE, date(2026, 9, 30))
    assert hit["eps"] == 32.87 and hit["how"] == "highlights sentence" and hit["period_end"] == date(2026, 9, 3)
    assert "$32.87 per diluted share" in hit["evidence"]
    hit = V.parse_release_eps(TABLE_ONLY)
    assert hit["eps"] == 1.84 and hit["how"] == "diluted EPS row" and hit["period_end"] == date(2026, 6, 30)   # the non-GAAP row is skipped
    assert V.parse_release_eps("Revenue grew nicely. Adjusted diluted earnings per share $ 3.00") is None
    assert V.parse_release_eps("") is None


def q(end, eps, filed, start=None, form="10-Q"):
    return {"end": end, "start": start or (end.replace(month=end.month - 2) if end.month > 2 else end.replace(year=end.year - 1, month=end.month + 10)),
            "eps": eps, "filed": filed, "form": form, "derived": False, "source": "xbrl"}


MU_Q = [q(date(2025, 8, 28), 2.83, date(2025, 10, 3), form="10-K"), q(date(2025, 11, 27), 4.60, date(2025, 12, 18), start=date(2025, 8, 29)), q(date(2026, 2, 26), 12.07, date(2026, 3, 19)),
        q(date(2026, 5, 28), 24.67, date(2026, 6, 25))]


def test_eps_quarters_derives_the_fourth_quarter_from_the_annual_fact():
    facts = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        {"start": "2025-01-01", "end": "2025-03-31", "val": 1.0, "filed": "2025-05-01", "form": "10-Q"},
        {"start": "2025-04-01", "end": "2025-06-30", "val": 1.1, "filed": "2025-08-01", "form": "10-Q"},
        {"start": "2025-07-01", "end": "2025-09-30", "val": 1.2, "filed": "2025-11-01", "form": "10-Q"},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 4.6, "filed": "2026-02-15", "form": "10-K"},
        {"start": "2025-01-01", "end": "2025-06-30", "val": 2.1, "filed": "2025-08-01", "form": "10-Q"},      # a six-month fact is neither
    ]}}}}}
    qs = V.eps_quarters(facts)
    assert [(x["end"].isoformat(), x["eps"], x["derived"]) for x in qs] == [("2025-03-31", 1.0, False), ("2025-06-30", 1.1, False), ("2025-09-30", 1.2, False), ("2025-12-31", 1.3, True)]


def test_the_window_must_hold_the_latest_reported_quarter():
    today = date(2026, 10, 7)
    four, why = V.fresh_window(MU_Q, date(2026, 9, 30), None, today)
    assert four is None and "release EPS is not stored" in why                                           # Sep 30 reported, XBRL through May 28
    four, why = V.fresh_window(MU_Q, date(2026, 9, 30), {"eps": 32.87, "period_end": date(2026, 9, 3), "accession": "0000723125-26-000018"}, today)
    assert [x["eps"] for x in four] == [4.60, 12.07, 24.67, 32.87] and four[-1]["source"] == "release" and why.startswith("three XBRL")
    assert V.pe(1063.96, four) == 14.34 and V.period_label(four) == "2025-08-29 to 2026-09-03"
    stale = MU_Q[:2]  + [q(date(2025, 12, 31), 1.0, date(2026, 2, 20))]                               # XBRL two quarters behind: no window
    four, why = V.fresh_window(stale, date(2026, 7, 14), {"eps": 2.0, "period_end": date(2026, 6, 30), "accession": "x"}, today)
    assert four is None and "more than one quarter behind" in why
    four, why = V.fresh_window(MU_Q, date(2026, 6, 25), None, today)                                   # the latest report is in XBRL already
    assert [x["eps"] for x in four] == [2.83, 4.60, 12.07, 24.67] and why.startswith("XBRL holds")
    assert V.fresh_window(MU_Q[:3], None, None, today) == (None, "fewer than four reported quarters in XBRL")


def test_history_reports_median_and_share_above_and_counts_exclusions():
    bars = [(date(2026, 7, 1), 100.0), (date(2026, 7, 2), 1000.0), (date(2026, 7, 3), 120.0), (date(2026, 7, 6), 110.0)]
    qs = [q(date(2025, 9, 30), 2.0, date(2025, 11, 1)), q(date(2025, 12, 31), 2.0, date(2026, 2, 1)), q(date(2026, 3, 31), 2.0, date(2026, 5, 1)), q(date(2026, 6, 30), 2.0, date(2026, 6, 30))]
    h = V.pe_history(bars, qs, current=13.0)
    assert h["sessions"] == 3 and h["excluded"] == 1                                                  # 1000/8 = 125 is excluded (EPS under 1% of price)
    assert h["median"] == 13.8 and h["share_above"] == 33 and "min" not in h and "max" not in h
    neg = [q(date(2025, 9, 30), -7.0, date(2025, 11, 1))] + qs[1:]
    assert V.pe_history(bars, neg, 10.0)["excluded"] == 4                                              # negative trailing EPS


def test_release_against_xbrl_and_the_checkers_match():
    assert V.release_difference(32.87, 32.87) == (0.0, False)
    assert V.release_difference(32.87, 32.99) == (-0.12, True)
    assert V.release_difference(1.84, 1.85) == (-0.01, False)
    later = MU_Q + [q(date(2026, 9, 3), 32.87, date(2026, 10, 20), form="10-K")]
    assert matching_quarter(later, date(2026, 9, 3), date(2026, 9, 30))["eps"] == 32.87
    assert matching_quarter(later, None, date(2026, 9, 30))["eps"] == 32.87                          # newest quarter before the report, filed after it
    assert matching_quarter(MU_Q, date(2026, 9, 3), date(2026, 9, 30)) is None                        # not filed yet
    # PANW: the fourth quarter exists in XBRL only as the 10-K's annual figure less three 10-Qs; it is never the match, and the row reads not comparable
    derived = {**q(date(2026, 7, 31), -0.46, date(2026, 9, 10), form="10-K"), "derived": True}
    panw = MU_Q + [derived]
    assert matching_quarter(panw, date(2026, 7, 31), date(2026, 8, 18)) is None
    assert derived_only_match(panw, date(2026, 7, 31), date(2026, 8, 18)) is derived
    assert derived_only_match(MU_Q, date(2026, 7, 31), date(2026, 8, 18)) is None
    assert matching_quarter(MU_Q + [{**q(date(2026, 7, 31), -0.35, date(2026, 9, 10), form="10-K")}, derived], date(2026, 7, 31), date(2026, 8, 18))["eps"] == -0.35   # a direct figure wins
    assert exhibit_text([("form8k.htm", "x" * 600), ("a2026q4ex991-pressrelease.htm", "y" * 600)])[0] == "a2026q4ex991-pressrelease.htm"


def test_snapshot_states_ok_not_meaningful_or_missing_with_reasons():
    today = date(2026, 10, 7)
    rel = {"eps": 32.87, "period_end": date(2026, 9, 3), "accession": "0000723125-26-000018"}
    s = V.snapshot(1063.96, MU_Q, date(2026, 9, 30), rel, today)
    assert s["status"] == "ok" and s["pe"] == 14.34 and s["window_start"] == date(2025, 8, 29) and s["window_end"] == date(2026, 9, 3)
    assert s["quarters"][-1]["source"] == "release" and s["quarters"][-1]["form"].startswith("earnings release 8-K 0000723125")
    s = V.snapshot(1063.96, MU_Q, date(2026, 9, 30), None, today)
    assert s["status"] == "missing" and "release EPS is not stored" in s["reason"] and s["pe"] is None
    loss = [{**q, "eps": -1.0} for q in MU_Q]
    s = V.snapshot(50.0, loss, date(2026, 6, 25), None, today)
    assert s["status"] == "not_meaningful" and s["reason"] == "lost money over the last four quarters" and s["trailing_eps"] == -4.0 and s["window_end"] == date(2026, 5, 28)
    assert V.snapshot(None, MU_Q, date(2026, 6, 25), None, today)["reason"] == "no stored close"
    tiny = [{**q, "eps": 0.05} for q in MU_Q]                                                    # trailing 0.20 under a 50 close: P/E 250
    s = V.snapshot(50.0, tiny, date(2026, 6, 25), None, today)
    assert s["status"] == "not_meaningful" and s["pe"] == 250.0 and s["reason"] == "earnings near zero: P/E above 100" and V.PE_MAX_MEANINGFUL == 100


def test_sector_median_shows_only_at_ninety_percent_coverage():
    statuses = [("ok", 10.0)] * 8 + [("not_meaningful", None)] * 1
    s = V.sector_summary(statuses, active=10)
    assert s["shown"] and s["median_pe"] == 10.0 and s["fresh"] == 9 and s["with_pe"] == 8          # 9 of 10 fresh windows
    s = V.sector_summary(statuses[:8], active=10)
    assert not s["shown"] and "8 of 10" in s["reason"] and "90%" in s["reason"]                      # 80% is not enough; the median is still computed
    assert V.sector_summary([], active=0)["reason"] == "no active tickers"


def test_quarters_are_reread_only_while_a_recent_report_may_not_have_landed():
    today = date(2026, 10, 7)
    assert V.needs_refresh([], None, today)                                                           # nothing stored
    assert V.needs_refresh(MU_Q, date(2026, 9, 30), today)                                            # Sep 30 reported, XBRL through May
    assert not V.needs_refresh(MU_Q, date(2026, 6, 25), today)                                       # the latest report is in XBRL
    later = MU_Q + [q(date(2026, 9, 3), 32.87, date(2026, 10, 20), form="10-K")]
    assert not V.needs_refresh(later, date(2026, 9, 30), today)
    assert not V.needs_refresh(MU_Q, date(2026, 5, 1), date(2026, 12, 1))                            # an old report never triggers a reread


def test_release_parser_reads_the_other_common_phrasings():
    assert V.parse_release_eps("Net income of $1.84 billion, or $2.75 per diluted share, compared to $2.87 per diluted share last year.")["eps"] == 2.75
    assert V.parse_release_eps("Earnings per Share: GAAP: $0.99; Non-GAAP: $1.02. GAAP EPS increased 52%.")["eps"] == 0.99
    assert V.parse_release_eps("Diluted EPS $4.22, up 13% versus prior year.")["eps"] == 4.22
    assert V.parse_release_eps("Earnings per share—basic $ 4.31 Earnings per share—diluted $ 4.22")["eps"] == 4.22
    assert V.parse_release_eps("Chubb Reports Second Quarter Per Share Net Income of $7.30. Net income was $2.9 billion, or $7.30 per share, and core operating income of $2.26 per share.")["eps"] == 7.30
    assert V.parse_release_eps("Adjusted net income of $2.0 billion, or $3.10 per diluted share.") is None        # adjusted is never GAAP
    assert V.parse_release_eps("GAAP net loss of $(0.18). Non-GAAP EPS of $0.78 increased.") is None                # "Non-GAAP EPS" is not a GAAP label
    old_first = "Results for the quarter ended March 31, 2025 were restated. For the quarter ended June 30, 2026, diluted earnings per share $ 1.36 $ 1.31."
    assert V.parse_release_eps(old_first, date(2026, 7, 29))["period_end"] == date(2026, 6, 30)                   # a comparison period is skipped
    assert V.parse_release_eps("Business Outlook for fiscal 2027: Diluted Earnings Per Share $14.39 – $14.81, a 6% to 9% increase.") is None   # guidance, a range
    assert V.parse_release_eps("Q1 FY 2027 Guidance: Earnings per Share: GAAP: $1.02 to $1.07.") is None
    assert V.parse_release_eps("16 Weeks Ended August 30, 2026. Net income was $2.998 billion, $6.75 per diluted share, compared to $5.87 last year.")["period_end"] == date(2026, 8, 30)
    assert V.parse_release_eps("Core operating income of $2.26 per diluted share.") is None
    assert exhibit_text([("0000037996-26-000155-index-headers.html", "x" * 7000), ("exhibit99tojuly282026for.htm", "y" * 600)])[0] == "exhibit99tojuly282026for.htm"


def test_a_corporate_action_inside_the_window_means_not_meaningful_yet_and_leaves_history():
    today = date(2026, 10, 7)
    rel = {"eps": 32.87, "period_end": date(2026, 9, 3), "accession": "x"}
    spin = [{"kind": "spin_off", "date": date(2026, 6, 29), "name": "Solstice"}]
    s = V.snapshot_with_actions(1063.96, MU_Q, date(2026, 9, 30), rel, today, spin)
    assert s["status"] == "not_meaningful_yet" and s["pe"] is None and s["reason"] == "Spun off Solstice on Jun 29, 2026; 4 full quarters after it are needed"
    assert V.snapshot_with_actions(1063.96, MU_Q, date(2026, 9, 30), rel, today, [{"kind": "spin_off", "date": date(2025, 6, 1), "name": None}])["status"] == "ok"   # before the window
    after = [{"kind": "merger", "date": date(2026, 10, 5), "name": "AvalonBay"}]                                                              # after the window, before the price
    assert V.snapshot_with_actions(1063.96, MU_Q, date(2026, 9, 30), rel, today, after)["status"] == "not_meaningful_yet"
    alias = [{"kind": "rename_merge", "date": date(2026, 10, 7), "name": "PSKY"}]                                                             # a symbol change with no deal behind it holds nothing
    assert V.snapshot_with_actions(1063.96, MU_Q, date(2026, 9, 30), rel, today, alias)["status"] == "ok"
    assert V.action_reason({"kind": "rename_merge", "date": date(2026, 10, 5), "name": "EQR"}) == "Renamed from EQR on Oct 5, 2026 after a merger; 4 full quarters after it are needed"
    assert V.action_reason({"kind": "spin_off", "date": date(2026, 1, 5), "name": None}).startswith("Spun off a business on Jan 5, 2026")
    s = V.sector_summary([("ok", 10.0)] * 8 + [("not_meaningful_yet", None)] * 2, active=10)
    assert s["shown"] and s["with_pe"] == 8 and s["fresh"] == 10                              # covered, but out of the median
    bars = [(date(2026, 7, 1), 100.0), (date(2026, 7, 2), 110.0), (date(2026, 7, 3), 120.0)]
    qs = [q(date(2025, 9, 30), 2.0, date(2025, 11, 1)), q(date(2025, 12, 31), 2.0, date(2026, 2, 1)), q(date(2026, 3, 31), 2.0, date(2026, 5, 1)), q(date(2026, 6, 30), 2.0, date(2026, 6, 30))]
    h = V.pe_history_clean(bars, qs, 13.0, [date(2026, 1, 15)])
    assert h["sessions"] == 0 and h["excluded"] == 3                                           # every window holds the action
    assert V.pe_history_clean(bars, qs, 13.0, [date(2024, 1, 1)])["sessions"] == 3


def test_share_counts_and_jumps_without_a_recorded_action():
    facts = {"facts": {"us-gaap": {"WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
        {"start": "2026-01-01", "end": "2026-03-31", "val": 1000.0, "filed": "2026-05-01"}, {"start": "2026-04-01", "end": "2026-06-30", "val": 850.0, "filed": "2026-08-01"},
        {"start": "2026-01-01", "end": "2026-06-30", "val": 925.0, "filed": "2026-08-01"}]}}}}}
    assert V.share_quarters(facts) == {date(2026, 3, 31): 1000.0, date(2026, 6, 30): 850.0}
    qs = [{"end": date(2026, 3, 31), "start": date(2026, 1, 1), "diluted_shares": 1000.0}, {"end": date(2026, 6, 30), "start": date(2026, 4, 1), "diluted_shares": 850.0},
          {"end": date(2026, 9, 30), "start": date(2026, 7, 1), "diluted_shares": 845.0}]
    jumps = V.share_jumps(qs, [])
    assert len(jumps) == 1 and jumps[0]["change_pct"] == -15.0 and jumps[0]["to_end"] == date(2026, 6, 30)
    assert V.share_jumps(qs, [date(2026, 5, 15)]) == []                                          # a recorded action between them explains it
    flip = [{"end": date(2026, 3, 31), "start": date(2026, 1, 1), "diluted_shares": 815_000_000.0}, {"end": date(2026, 6, 30), "start": date(2026, 4, 1), "diluted_shares": 32_558_000.0}]
    assert V.share_jumps(flip, []) == []                                                          # a units flip in the facts, not an action
    nflx = [{"end": date(2025, 6, 30), "start": date(2025, 4, 1), "diluted_shares": 4_348_825_000.0}, {"end": date(2025, 9, 30), "start": date(2025, 7, 1), "diluted_shares": 434_039_000.0}]
    assert V.share_jumps(nflx, [], [(date(2025, 11, 17), 10.0)]) == []                              # a 10:1 split two months later restated the September quarter
    assert len(V.share_jumps(nflx, [], [(date(2025, 11, 17), 5.0)])) == 1                           # a split of another ratio explains nothing
    assert V.split_ratio("10:1") == 10.0 and V.split_ratio("1:5") == 0.2 and V.split_ratio("x") is None


def test_edgar_backoff_ladder_and_retry_after():
    from app.services.edgar_client import RETRY_DELAYS_S, backoff_delay
    assert backoff_delay(0, None) == RETRY_DELAYS_S[0] and backoff_delay(2, None) == RETRY_DELAYS_S[2]
    assert backoff_delay(3, None) is None                                                         # no retry left
    assert backoff_delay(0, "7") == 7.0 and backoff_delay(0, "0") == 1.0 and backoff_delay(1, "soon") == RETRY_DELAYS_S[1]


def test_an_eps_fact_that_is_a_dollar_amount_is_dropped():
    """ICE's 2015 10-Qs tag $112,000,000 as EarningsPerShareDiluted; the value overflowed eps_quarters and blocked the ticker's reread."""
    facts = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        {"start": "2015-01-01", "end": "2015-03-31", "filed": "2016-05-04", "val": 112000000.0, "form": "10-Q"},
        {"start": "2015-04-01", "end": "2015-06-30", "filed": "2015-08-05", "val": 0.81, "form": "10-Q"},
        {"start": "2015-01-01", "end": "2015-12-31", "filed": "2016-02-04", "val": 112000000.0, "form": "10-K"}]}}}}}
    qs = V.eps_quarters(facts)
    assert [(q["end"].isoformat(), q["eps"]) for q in qs] == [("2015-06-30", 0.81)]
    assert V.EPS_FACT_MAX >= 50_000                                                     # Berkshire's class A figure stays


def test_quarters_and_closes_are_restated_across_recorded_splits():
    """BKNG's 25:1 split of 2026-04-06: the 10-K filed in February carries the old basis, the 10-Qs filed after it the new one; a derived
    quarter is computed after the restatement, and a close before the split is divided like the quarters."""
    splits = [(date(2026, 4, 6), 25.0)]
    facts = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        {"start": "2025-01-01", "end": "2025-03-31", "filed": "2026-04-28", "val": 0.40, "form": "10-Q"},      # restated after the split
        {"start": "2025-04-01", "end": "2025-06-30", "filed": "2026-08-04", "val": 1.10, "form": "10-Q"},      # restated after the split
        {"start": "2025-07-01", "end": "2025-09-30", "filed": "2025-10-28", "val": 84.41, "form": "10-Q"},     # old basis
        {"start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-18", "val": 165.00, "form": "10-K"},    # old basis: the year
        {"start": "2026-01-01", "end": "2026-03-31", "filed": "2026-04-28", "val": 1.36, "form": "10-Q"},
        {"start": "2026-04-01", "end": "2026-06-30", "filed": "2026-08-04", "val": 2.53, "form": "10-Q"}]}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [{"start": "2025-07-01", "end": "2025-09-30", "filed": "2025-10-28", "val": 32558000}]}}}}}
    qs = V.eps_quarters(facts, splits)
    by = {q["end"].isoformat(): q for q in qs}
    assert by["2025-09-30"]["eps"] == 3.3764 and by["2025-09-30"]["rebased"] == "25:1 split of 2026-04-06" and by["2025-09-30"]["diluted_shares"] == 32558000 * 25
    assert by["2025-12-31"]["derived"] and by["2025-12-31"]["eps"] == round(165.0 / 25 - (0.40 + 1.10 + 3.3764), 4) and by["2025-12-31"]["rebased"]
    assert "rebased" not in by["2026-03-31"] and by["2026-03-31"]["eps"] == 1.36
    four = [by[k] for k in ("2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30")]
    assert 15 < V.pe(157.63, four) < 20                                                     # a sane P/E, not 0.94
    assert V.eps_quarters(facts)[2]["eps"] == 84.41                                          # no splits known: as filed
    assert V.rebase_closes([(date(2026, 4, 1), 5000.0), (date(2026, 4, 7), 200.0)], splits) == [(date(2026, 4, 1), 200.0), (date(2026, 4, 7), 200.0)]
    assert V.split_factor(date(2026, 1, 1), [(date(2026, 2, 1), 0.2)]) == (0.2, ["1:5 reverse split of 2026-02-01"])     # a reverse split multiplies
    assert V.split_factor(date(2026, 1, 1), [(date(2026, 2, 1), None)]) == (1.0, [])                                      # unreadable ratio: left alone
    assert V.PE_COMPUTATION_VERSION == 2
