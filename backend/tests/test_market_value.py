from datetime import date

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
