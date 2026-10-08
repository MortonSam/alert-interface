"""The S&P 500 membership rule: a scraped change takes effect only when SPY's holdings agree or the scrape shows it two nights running;
a row carrying another stored ticker's CIK changes nothing. 2026-10-08: one scrape deactivated CTVA and added VYLR the same night
(right, as SPY's Oct 7 holdings showed, but unconfirmed when it happened)."""
import io
import zipfile
from datetime import date

from app.services.index_membership import cik_conflicts, decide, parse_spy_holdings

TODAY = date(2026, 10, 9)
ACTIVE = {"AAPL", "CTVA", "MSFT"}


def test_a_change_takes_effect_with_spy_agreeing():
    d = decide({"AAPL", "MSFT", "VYLR"}, ACTIVE, {"AAPL", "MSFT", "VYLR"}, {}, TODAY)
    assert d.leave == ["CTVA"] and d.join == ["VYLR"] and not d.pending_leave and not d.pending_join
    assert d.why["CTVA"] == "missing from the constituent list and from SPY's holdings"


def test_without_a_second_source_a_change_waits_one_night_then_takes_effect():
    d = decide({"AAPL", "MSFT", "VYLR"}, ACTIVE, None, {}, TODAY)
    assert d.leave == [] and d.join == [] and d.pending_leave == {"CTVA": "2026-10-09"} and d.pending_join == {"VYLR": "2026-10-09"}
    d2 = decide({"AAPL", "MSFT", "VYLR"}, ACTIVE, None, {"leave": d.pending_leave, "join": d.pending_join}, date(2026, 10, 10))
    assert d2.leave == ["CTVA"] and d2.join == ["VYLR"] and "two nights" in d2.why["CTVA"]
    # a name back on the list the next night resets; the same night twice never counts as two
    assert decide({"AAPL", "MSFT", "CTVA"}, ACTIVE, None, {"leave": d.pending_leave}, date(2026, 10, 10)).pending_leave == {}
    assert decide({"AAPL", "MSFT"}, ACTIVE, None, {"leave": d.pending_leave}, TODAY).leave == []


def test_spy_disagreeing_holds_the_change():
    d = decide({"AAPL", "MSFT", "VYLR"}, ACTIVE, {"AAPL", "MSFT", "CTVA"}, {}, TODAY)
    assert d.leave == [] and d.join == [] and "SPY still holds it" in d.why["CTVA"] and "not in SPY" in d.why["VYLR"]


def test_a_row_carrying_another_stored_tickers_cik_is_a_conflict():
    owners = {"0000906107": {"VMRK"}, "0002128626": {"VYLR"}, "0001652044": {"GOOG", "GOOGL"}}
    rows = [{"symbol": "VYLR", "cik": "0000906107"}, {"symbol": "GOOGL", "cik": "0001652044"}, {"symbol": "GOOG", "cik": "1652044"},
            {"symbol": "NEWCO", "cik": "0009999999"}, {"symbol": "AAPL", "cik": ""}]
    assert cik_conflicts(rows, owners, {"VMRK", "GOOG", "GOOGL"}) == {"VYLR": "CIK 0000906107 belongs to VMRK, not VYLR"}
    assert cik_conflicts([{"symbol": "VYLR", "cik": "0002128626"}], owners, {"VMRK"}) == {}


def test_the_spy_file_is_read_without_a_spreadsheet_library():
    strings = ["Fund Name:", "SPY", "Holdings:", "As of 07-Oct-2026", "Name", "Ticker", "VYLOR INC", "VYLR", "BERKSHIRE HATHAWAY INC CL B", "BRK.B", "US DOLLAR", "-"]
    ss = "<sst>" + "".join(f"<si><t>{x}</t></si>" for x in strings) + "</sst>"
    def row(i, a, b):
        return f'<row r="{i}"><c r="A{i}" t="s"><v>{a}</v></c><c r="B{i}" t="s"><v>{b}</v></c></row>'
    sheet = "<worksheet><sheetData>" + row(1, 0, 1) + row(2, 2, 3) + row(3, 4, 5) + row(4, 6, 7) + row(5, 8, 9) + row(6, 10, 11) + "</sheetData></worksheet>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", ss)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    held, as_of = parse_spy_holdings(buf.getvalue())
    assert held == {"VYLR", "BRK-B"} and as_of == "As of 07-Oct-2026"
