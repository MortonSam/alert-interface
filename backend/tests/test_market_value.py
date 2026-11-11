from datetime import date

import pytest

from app.services import market_value as MV


def _ctx(cid: str, instant: str, *members: tuple[str, str]) -> str:
    dims = "".join(f'<xbrldi:explicitMember dimension="{a}">{m}</xbrldi:explicitMember>' for a, m in members)
    seg = f"<xbrli:segment>{dims}</xbrli:segment>" if dims else ""
    return f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier>{seg}</xbrli:entity><xbrli:period><xbrli:instant>{instant}</xbrli:instant></xbrli:period></xbrli:context>'


def _fact(cid: str, value: str, scale: int = 0, fmt: str = "ixt:num-dot-decimal") -> str:
    return f'<ix:nonFraction unitRef="shares" contextRef="{cid}" name="dei:EntityCommonStockSharesOutstanding" format="{fmt}" scale="{scale}">{value}</ix:nonFraction>'


AXIS = "us-gaap:StatementClassOfStockAxis"


def test_every_class_on_the_cover_is_summed_once():
    # Alphabet's 10-Q of Oct 29, 2026: three classes, in millions; companyfacts carries none of them
    html = (_ctx("c-28", "2026-10-21", (AXIS, "us-gaap:CommonClassAMember")) + _ctx("c-29", "2026-10-21", (AXIS, "us-gaap:CommonClassBMember"))
            + _ctx("c-30", "2026-10-21", (AXIS, "goog:CapitalClassCMember")) + _fact("c-28", "5,888", 6) + _fact("c-29", "827", 6)
            + _fact("c-30", "5,579", 6) + _fact("c-28", "5,888", 6))
    c = MV.cover_shares(html)
    assert c["as_of"] == date(2026, 10, 21) and c["total"] == 12_294_000_000


def test_a_total_units_preferred_and_a_co_registrant_are_not_classes():
    html = (_ctx("a", "2026-10-31", (AXIS, "us-gaap:CommonStockMember")) + _ctx("b", "2026-10-31", (AXIS, "blk:FullyDilutedSharesMember"))
            + _ctx("c", "2026-10-31", (AXIS, "blk:ExchangeableUnitsMember")) + _ctx("d", "2026-10-31", (AXIS, "us-gaap:SeriesBPreferredStockMember"))
            + _ctx("e", "2026-10-31", ("dei:LegalEntityAxis", "pcg:UtilityMember")) + _fact("a", "154,417,000") + _fact("b", "162,030,000")
            + _fact("c", "7,613,000") + _fact("d", "30,000,000") + _fact("e", "264,374,809"))
    assert MV.cover_shares(html)["total"] == 154_417_000


def test_one_undimensioned_figure_stands_alone_and_berkshire_a_counts_as_1500_b():
    assert MV.cover_shares(_ctx("x", "2026-10-23", ) + _fact("x", "14,532,182,000"))["total"] == 14_532_182_000
    brk = {"classes": [("CommonClassAMember", 480_000), ("CommonClassBMember", 1_403_810_000)]}
    assert MV.priced_shares("BRK-B", brk) == 480_000 * 1500 + 1_403_810_000
    assert MV.priced_shares("GOOGL", brk) == 480_000 + 1_403_810_000
    assert MV.cover_shares(_ctx("z", "2026-10-23") + _fact("z", "—", fmt="ixt:fixed-zero"))["total"] == 0
    assert MV.cover_shares("<html></html>") is None


GOOGL_COVER = {"as_of": date(2026, 10, 21), "classes": [("us-gaap:CommonClassAMember", 5_888e6), ("us-gaap:CommonClassBMember", 827e6), ("goog:CapitalClassCMember", 5_579e6)],
               "total": 12_294e6}
DAY = date(2026, 11, 9)


def test_each_class_is_priced_by_its_own_close_and_both_symbols_carry_one_figure():
    closes = {"GOOGL": (DAY, 290.0), "GOOG": (DAY, 291.0)}
    a, c = MV.company_value("GOOGL", GOOGL_COVER, closes), MV.company_value("GOOG", GOOGL_COVER, closes)
    assert a == c and a["company"] == "GOOGL" and a["held_reason"] is None and a["close_date"] == DAY
    assert a["value"] == 5_888e6 * 290.0 + 827e6 * 290.0 + 5_579e6 * 291.0           # Class B, unlisted, at Class A's close
    assert [x["priced_by"] for x in a["classes"]] == ["GOOGL", "GOOGL", "GOOG"]
    assert MV.company_of("GOOG") == "GOOGL" and MV.company_symbols("GOOG") == ["GOOGL", "GOOG"] and MV.company_of("NVDA") == "NVDA"
    brk = {"as_of": date(2026, 10, 23), "classes": [("us-gaap:CommonClassAMember", 480_000.0), ("us-gaap:CommonClassBMember", 1_403_810_000.0)], "total": 0}
    assert MV.company_value("BRK-B", brk, {"BRK-B": (DAY, 500.0)})["value"] == (480_000 * 1500 + 1_403_810_000) * 500.0
    one = {"as_of": date(2026, 10, 23), "classes": [("", 14_532_182_000.0)], "total": 14_532_182_000.0}
    assert MV.company_value("AAPL", one, {"AAPL": (DAY, 270.0)})["value"] == 14_532_182_000.0 * 270.0


def test_no_figure_without_every_class_priced_or_after_a_split_or_without_a_cover():
    assert MV.company_value("GOOGL", GOOGL_COVER, {"GOOGL": (DAY, 290.0)}) | {"classes": []} == {
        "company": "GOOGL", "value": None, "held_reason": MV.NO_CLOSE, "shares": 12_294e6, "shares_as_of": date(2026, 10, 21), "close_date": None, "classes": []}
    one = {"as_of": date(2026, 10, 23), "classes": [("", 1e9)], "total": 1e9}
    assert MV.company_value("NVDA", one, {"NVDA": (DAY, 100.0)}, split_after=date(2026, 10, 30))["held_reason"] == MV.SPLIT
    assert MV.company_value("NVDA", one, {"NVDA": (DAY, 100.0)}, split_after=date(2026, 10, 1))["value"] == 1e11       # a split the cover already carries
    assert MV.company_value("VYLR", None, {"VYLR": (DAY, 30.0)}) | {"classes": []} == {
        "company": "VYLR", "value": None, "held_reason": MV.NO_COVER, "shares": None, "shares_as_of": None, "close_date": None, "classes": []}
    # a class with no shares needs no price
    zero = {"as_of": date(2026, 10, 23), "classes": [("us-gaap:CommonClassAMember", 1e9), ("us-gaap:CommonClassBMember", 0.0)], "total": 1e9}
    assert MV.company_value("NWSA", zero, {"NWSA": (DAY, 30.0)})["value"] == 3e10
    # a halted symbol's old close prices nothing
    assert MV.fresh_closes({"A": (DAY, 1.0), "B": (date(2026, 11, 2), 2.0), "C": (date(2026, 10, 30), 3.0)}) == {"A": (DAY, 1.0), "B": (date(2026, 11, 2), 2.0)}


def test_the_hold_out_list_gets_no_figure_and_a_dated_hold_lifts_on_a_newer_cover():
    one = lambda day: {"as_of": day, "classes": [("", 1e9)], "total": 1e9}
    for sym, (reason, held_on) in MV.HELD.items():
        v = MV.company_value(sym, one(held_on or date(2026, 10, 30)), {s: (DAY, 50.0) for s in MV.company_symbols(sym)})
        assert v["value"] is None and v["held_reason"] == reason, sym
    assert MV.company_value("V", one(date(2027, 1, 30)), {"V": (DAY, 50.0)})["value"] is None                  # an undated hold stands
    assert MV.held_reason("KMB", one(date(2026, 10, 29))) == MV.MERGER and MV.held_reason("KMB", one(date(2027, 1, 22))) is None
    assert MV.company_value("LULU", one(date(2026, 11, 27)), {"LULU": (DAY, 200.0)})["value"] == 2e11
    assert MV.held_reason("NVDA", None) is None


def test_a_hold_on_one_symbol_holds_the_company_and_fox_is_not_held(monkeypatch):
    fox = {"as_of": date(2026, 10, 28), "classes": [("us-gaap:CommonClassAMember", 201.55e6), ("us-gaap:CommonClassBMember", 220.25e6)], "total": 421.8e6}
    closes = {"FOXA": (DAY, 66.0), "FOX": (DAY, 62.0)}
    assert "FOX" not in MV.HELD and "FOXA" not in MV.HELD                                                       # Sam, 2026-11-11: the hold is lifted
    for sym in ("FOX", "FOXA"):                                                                                 # each class at its own close, one figure for both
        v = MV.company_value(sym, fox, closes)
        assert v["company"] == "FOXA" and v["held_reason"] is None and v["value"] == 201.55e6 * 66.0 + 220.25e6 * 62.0
    monkeypatch.setitem(MV.HELD, "FOX", (MV.MERGER, date(2026, 10, 28)))
    assert MV.held_reason("FOX", fox) == MV.held_reason("FOXA", fox) == MV.MERGER                               # either symbol holds the company
    assert MV.company_value("FOXA", fox, closes)["value"] is None


def test_a_cover_on_file_is_read_again_from_its_row():
    from app.scripts.compute_market_values import stored_cover
    row = {"classes": [{"member": "us-gaap:CommonClassAMember", "shares": 5_888e6, "priced_by": "GOOGL"}, {"member": "goog:CapitalClassCMember", "shares": 5_579e6}],
           "shares_as_of": date(2026, 10, 21)}
    assert stored_cover(row) == {"as_of": date(2026, 10, 21), "classes": [("us-gaap:CommonClassAMember", 5_888e6), ("goog:CapitalClassCMember", 5_579e6)], "total": 11_467e6}
    assert stored_cover({"classes": [], "shares_as_of": None}) is None and stored_cover(None) is None


def test_the_header_serves_the_companys_own_figure_and_never_the_vendors(monkeypatch):
    import uuid
    from datetime import datetime, timezone
    from app.config import settings
    from app.schemas.ticker import TickerRead
    from app.services import market_value_store as S
    now = datetime.now(timezone.utc)
    read = lambda sym: TickerRead(id=uuid.uuid4(), symbol=sym, market_cap=5_160_000_000_000, created_at=now, updated_at=now)
    figures = {"GOOG": {"value": 3_530_580_000_000.4, "close_date": DAY}}
    monkeypatch.setattr(settings, "personal_use_data_shown", False)
    got = S.show(read("GOOG"), figures).model_dump()
    assert got["market_cap"] == 3_530_580_000_000 and got["market_cap_as_of"] == DAY and got["market_cap_basis"] == S.FILINGS
    held = S.show(read("V"), figures).model_dump()
    assert held["market_cap"] is None and held["market_cap_as_of"] is None                        # no figure: nothing, not the vendor's
    # with the flag on, a response that never passed through show() still withholds the vendor's, even with personal-use data shown
    monkeypatch.setattr(settings, "personal_use_data_shown", True)
    monkeypatch.setattr(settings, "market_value_enabled", True)
    assert read("V").model_dump()["market_cap"] is None and S.show(read("V"), figures).model_dump()["market_cap"] is None
    monkeypatch.setattr(settings, "market_value_enabled", False)
    assert read("V").model_dump()["market_cap"] == 5_160_000_000_000                              # the flag off: as before


def test_the_overview_says_the_companys_own_value_or_nothing():
    from app.services import briefing as B
    from app.services.briefing import fmt_date
    base = dict(name="Alphabet Inc.", symbol="GOOG", short_description="Alphabet runs Google.", profile_as_of=date(2026, 10, 5), gics_sector="Communication Services",
                index_member=True, quote_price=291.0, quote_ts=1_794_000_000, shares_outstanding=5_579e6, shares_as_of=date(2026, 10, 1), market_cap=1.6e12)
    own = {"value": 3_530.58e9, "close_date": DAY, "shares": 12_294e6, "shares_as_of": date(2026, 10, 21), "form": "10-Q", "filed": date(2026, 10, 29), "company": "GOOGL"}
    s = B.profile_sentence(**base, own_value_on=True, own_value=own)
    assert "worth about $3.5 trillion." in s["text"] and "market value" not in s["rule"] and "latest quote" not in s["rule"]   # no rule sentence is approved
    assert "membership from the nightly list. A merger into the company" in s["rule"] and not hasattr(B, "OWN_VALUE_RULE")
    inputs = {i["name"]: i for i in s["inputs"]}
    assert inputs["market cap"]["value"] == "$3.5 trillion" and inputs["market cap"]["source"] == B.OWN_VALUE_SOURCE and "quote" not in inputs
    assert inputs["shares outstanding"]["value"] == "12,294.0 million" and inputs["shares outstanding"]["source"] == f"the cover of its 10-Q filed {fmt_date(date(2026, 10, 29))}"
    none = B.profile_sentence(**base, own_value_on=True, own_value=None)                          # held: no clause, and never quote x the vendor's shares
    assert "worth about" not in none["text"] and "market cap" not in {i["name"] for i in none["inputs"]}
    brk = B.profile_sentence(**base, own_value_on=True, own_value={**own, "company": "BRK-B"})
    assert "shares outstanding" not in {i["name"] for i in brk["inputs"]}                         # its count is in Class B equivalents
    assert "stored" not in B.OWN_VALUE_SOURCE


def test_validate_flags_a_gap_over_ten_percent_only_with_equal_share_counts():
    from app.scripts.validate_data import CHECKS, check_market_value_sanity, check_market_value_vendor_gap, market_value_gaps
    row = lambda sym, value, shares, cap, vshares, company=None: {"symbol": sym, "company": company or sym, "value": value, "shares": shares, "vendor_cap": cap,
                                                                    "vendor_shares": vshares, "close_date": DAY, "vendor_at": date(2026, 11, 3)}
    rows = [row("AMD", 113.8e9, 1.63e9, 100e9, 1.63e9),            # 13.8% apart, same shares: flagged
            row("NVDA", 105e9, 1e9, 100e9, 1e9),                  # 5%: fine
            row("KMB", 60e9, 4.9e8, 100e9, 3.3e8),                # the shares differ: the hold-out list's business, not this check's
            row("GOOG", 3.5e12, 5.6e9, 1.6e12, 5.6e9, "GOOGL"),   # per company against per symbol: skipped
            row("V", None, 1.7e9, 600e9, 1.7e9),                  # no figure
            row("XOM", 672e9, 4.08e9, 763.8e9, 4.08e9)]           # the vendor's figure is the close of Oct 30: explained
    bad, old = market_value_gaps(rows, {"XOM": [(date(2026, 10, 30), 187.25), (date(2026, 11, 6), 165.87), (DAY, 164.73)], "AMD": [(date(2026, 11, 6), 64.0), (DAY, 69.8)]})
    assert len(bad) == 1 and bad[0].startswith("AMD: $113.8bn on file against the vendor's $100.0bn (+13.8%)")
    assert len(old) == 1 and old[0].startswith("XOM: ") and old[0].endswith("the vendor's figure is the close of 2026-10-30")
    assert market_value_gaps(rows)[1] == [] and len(market_value_gaps(rows)[0]) == 2          # with no closes to look in, both are unexplained
    assert check_market_value_vendor_gap in CHECKS and check_market_value_sanity in CHECKS


def test_the_nightly_computes_market_values_before_the_walkthrough():
    from app.scripts import compute_market_values, refresh
    labels = [label for label, _ in refresh.STEPS]
    assert labels.index("Price bars shadow (Intrinio)") < labels.index(compute_market_values.STEP_LABEL) < labels.index("Ivy walkthroughs")
    assert dict(refresh.STEPS)[compute_market_values.STEP_LABEL][-1] == "--write" and compute_market_values.STEP_LABEL in refresh.STEP_TIMEOUTS


def test_no_list_a_visitor_sees_is_ordered_by_the_vendors_market_cap():
    """Sam, 2026-11-11: a list ordered by size is ordered by the company's own figure, a company with none last, never the vendor's.
    The walkthrough (rival, featured pick, quick picks, compare stories, payload) and the emails do not read tickers.market_cap at
    all; the home grid and the search box sort by the figure the API serves, which MARKET_VALUE_ENABLED makes the company's own."""
    import pathlib, re
    app = pathlib.Path(__file__).resolve().parents[1] / "app"
    for rel in ("services/walkthrough_compare.py", "services/walkthrough_story.py", "services/walkthrough_data.py", "services/walkthrough.py",
                "routers/walkthrough.py", "scripts/build_walkthroughs.py", "services/emails.py"):
        assert not re.search(r"market_cap\b(?!_)", (app / rel).read_text()), rel
    for path in [*(app / "routers").glob("*.py"), *(app / "services").glob("*.py")]:
        assert not re.search(r"ORDER BY[^\n]*market_cap", path.read_text(), re.I), path.name
    from app.services import market_value_store as S
    assert "market_cap" not in S.TICKERS_WITH_VALUE and S.BY_SIZE == "mv.value DESC NULLS LAST, t.symbol"


@pytest.mark.asyncio
async def test_by_size_orders_by_the_figure_on_file_with_no_figure_last():
    from sqlalchemy import text
    from app.database import ScriptSessionLocal
    from app.services import market_value_store as S
    syms = ["AAPL", "MSFT", "NVDA", "V"]
    async with ScriptSessionLocal() as db:
        try:
            await db.execute(text("DELETE FROM market_values WHERE symbol = ANY(:s)"), {"s": syms})
            for sym, value in (("NVDA", 5.2e12), ("AAPL", 4.1e12), ("V", None)):               # Visa is held out; Microsoft has no row at all
                await db.execute(text("""INSERT INTO market_values (symbol, company, value, held_reason, version)
                    VALUES (:s, :s, :v, :r, :ver)"""), {"s": sym, "v": value, "r": None if value else MV.CONVERSION, "ver": MV.MARKET_VALUE_VERSION})
            got = (await db.execute(text(f"SELECT t.symbol FROM tickers t {S.SIZE_JOIN} WHERE t.symbol = ANY(:s) ORDER BY {S.BY_SIZE}"), {"s": syms})).scalars().all()
            assert got == ["NVDA", "AAPL", "MSFT", "V"]                                        # the two with no figure last, by symbol
        finally:
            await db.rollback()
