"""2026-10-13: the release EPS reader's column order comes from the exhibit (EIX's paraphrased heading no longer rejects an agreed
diluted figure), a basic row is refused when the release states diluted EPS and stored as basic when it states none (ED), the
readers that use the figure as diluted EPS read diluted rows only."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import release_reader as R
from app.services.valuation import basic_only_label, parse_release_basic_eps, parse_release_eps, release_period_end, states_diluted_eps

pytestmark = pytest.mark.xdist_group(name="shared_rows")

SCRIPTS = Path(__file__).resolve().parents[1] / "app" / "scripts"

# EIX 2026-07-30: a two-period table whose heading names both the three- and six-month columns; the model names only the quarter's
EIX = ("Consolidated Statements of Income Three months ended June 30, Six months ended June 30, (in millions, except per-share amounts, unaudited) "
       "2026 2025 2026 2025 Net income attributable to common shareholders $ 532 $ 343 $ 1,060 $ 1,780 "
       "Basic earnings per common share $ 1.38 $ 0.89 $ 2.75 $ 4.62 Diluted earnings per common share $ 1.38 $ 0.89 $ 2.75 $ 4.61")
EIX_QUOTE = "Diluted earnings per common share $ 1.38 $ 0.89 $ 2.75 $ 4.61"
EIX_PARAPHRASE = "Three months ended June 30, 2026 2025"
# ED 2026-08-06: no diluted EPS anywhere; "Dilutive effect" is not one
ED = ("Con Edison today reported 2026 second quarter net income for common stock of $308 million or $0.83 a share compared with $246 million "
      "or $0.68 a share in the 2025 second quarter. Adjusted earnings (non-GAAP) were $308 million or $0.83 a share. Dilutive effect of issuance "
      "of common shares. Attachment A For the Three Months Ended For the Six Months Ended June 30, June 30, Earnings per Share Net Income for "
      "Common Stock (Millions of Dollars) 2026 2025 2026 2025 Reported earnings per share (basic) and net income for common stock (GAAP basis) "
      "$0.83 $0.68 $308 $246 $3.37 $2.93 $1,232 $1,038 Adjusted earnings per share and adjusted earnings (non-GAAP basis) $0.83 $0.67")
ED_QUOTE = "Reported earnings per share (basic) and net income for common stock (GAAP basis) $0.83 $0.68"


def test_eix_column_order_comes_from_the_exhibit_and_a_paraphrased_heading_alone_is_a_note():
    # the exhibit's heading at the row is current-first, so column 1 is right whatever the model's heading says
    assert R.verify_quote(EIX, EIX_QUOTE, 1.38, EIX_PARAPHRASE, 1) == [R.HEADING_NOT_VERBATIM]
    figure, note = R.decide({"eps": 1.38, "how": "diluted EPS row"}, {"eps": 1.38, "quote": EIX_QUOTE, "columns": EIX_PARAPHRASE, "column": 1}, EIX)
    assert figure == 1.38
    assert note == "both readers +1.38; note: the model's heading is not verbatim in the exhibit (column order read from the exhibit)"
    # column 2 of a current-first table is the prior year: refused from the exhibit's heading even with no heading from the model
    assert "the heading lists the current period first but column 2 was read" in R.verify_quote(EIX, "Diluted earnings per common share $ 1.38 $ 0.89", 0.89, None, 2)


def test_the_heading_note_needs_exact_agreement_a_diluted_row_and_no_other_problem():
    model = {"eps": 1.38, "quote": EIX_QUOTE, "columns": EIX_PARAPHRASE, "column": 1}
    # the readers differ: rejected, as before
    figure, note = R.decide({"eps": 1.37, "how": "diluted EPS row"}, model, EIX)
    assert figure is None and "model quote rejected: the heading is not verbatim in the exhibit" in note
    # no pattern reading: rejected
    figure, note = R.decide(None, model, EIX)
    assert figure is None and "model quote rejected" in note
    # a basic row in a release that states no diluted EPS (ED), both readers exact: the paraphrased heading is a note
    ed_model = {"eps": 0.83, "quote": ED_QUOTE, "columns": "Three Months Ended 2026 2025", "column": 1}
    figure, note = R.decide({"eps": 0.83, "how": "basic EPS row"}, ed_model, ED)
    assert figure == 0.83 and note.endswith("note: the model's heading is not verbatim in the exhibit (column order read from the exhibit)")
    # the same basic row where the release states diluted EPS: refused (the basic-row rule), and readers that differ: rejected
    figure, note = R.decide({"eps": 0.83, "how": "basic EPS row"}, ed_model, ED + " Diluted earnings per share $0.82")
    assert figure is None and R.BASIC_ROW in note
    figure, note = R.decide({"eps": 0.82, "how": "basic EPS row"}, ed_model, ED)
    assert figure is None and "the heading is not verbatim in the exhibit" in note
    # another problem beside the heading: rejected
    figure, note = R.decide({"eps": 1.38, "how": "diluted EPS row"}, {**model, "column": None}, EIX)
    assert figure is None and "without the column read" in note
    assert R.diluted_row(EIX_QUOTE) and R.diluted_row("net income of $5 million, or $1.02 per diluted share") and not R.diluted_row(ED_QUOTE)


def test_a_basic_row_is_refused_when_the_release_states_diluted_eps():
    assert states_diluted_eps(EIX) and not states_diluted_eps(ED)
    assert basic_only_label("Reported earnings per share (basic)") and not basic_only_label("Basic and diluted earnings per share")
    # the model quoting EIX's basic row is refused; ED's basic row is not (ED states no diluted figure)
    assert R.BASIC_ROW in R.verify_quote(EIX, "Basic earnings per common share $ 1.38 $ 0.89 $ 2.75 $ 4.62", 1.38, None, 1)
    assert R.BASIC_ROW not in R.verify_quote(ED, ED_QUOTE, 0.83, None, 1)
    # the pattern parser skips a basic-labelled figure when a diluted one is stated, and reads the diluted one
    both = "Basic earnings per share were $1.00 for the quarter. Diluted earnings per share were $0.99 for the quarter."
    hit = parse_release_eps(both, None)
    assert hit is not None and hit["eps"] == 0.99


def test_ed_has_no_diluted_figure_so_its_basic_figure_is_read_as_basic():
    assert parse_release_eps(ED, date(2026, 8, 6)) is None
    hit = parse_release_basic_eps(ED, date(2026, 8, 6))
    assert hit is not None and hit["eps"] == 0.83 and hit["basis"] == "basic"
    assert parse_release_basic_eps(EIX, date(2026, 7, 30)) is None       # a release with diluted EPS never yields a basic figure
    # the seeder records the basis and stores a basic figure in basic_eps_gaap, never in diluted_eps_gaap
    seeder = (SCRIPTS / "seed_release_eps.py").read_text()
    assert 'basis = "diluted" if states_diluted_eps(ex[1]) else "basic"' in seeder
    assert '"dil": hit["eps"] if basis == "diluted" else None, "bas": hit["eps"] if basis == "basic" else None' in seeder
    # every reader that uses the figure as diluted EPS reads diluted rows only
    for script in ("compute_pe.py", "compute_growth.py", "check_release_eps.py", "valuation_report.py"):
        assert "eps_basis = 'diluted'" in (SCRIPTS / script).read_text(), script


@pytest.mark.asyncio
async def test_a_basic_row_stores_with_its_basis_and_the_table_refuses_a_basic_figure_in_the_diluted_column():
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM release_eps WHERE symbol = 'ZZED'"))
        await s.execute(text("""INSERT INTO release_eps (symbol, report_date, period_end, diluted_eps_gaap, basic_eps_gaap, eps_basis, how, evidence, accession, exhibit, filed_on)
                                VALUES ('ZZED', '2026-08-06', '2026-06-30', NULL, 0.83, 'basic', 'basic EPS row', 'x', '0000000000-26-000001', 'ex99', '2026-08-06')"""))
        await s.commit()
        assert (await s.execute(text("SELECT eps_basis, basic_eps_gaap, diluted_eps_gaap FROM release_eps WHERE symbol = 'ZZED'"))).one() == ("basic", Decimal("0.8300"), None)
        with pytest.raises(Exception):
            await s.execute(text("""INSERT INTO release_eps (symbol, report_date, period_end, diluted_eps_gaap, basic_eps_gaap, eps_basis, how, evidence, accession, exhibit, filed_on)
                                    VALUES ('ZZED', '2026-05-06', '2026-03-31', 0.70, NULL, 'basic', 'basic EPS row', 'x', '0000000000-26-000002', 'ex99', '2026-05-06')"""))
        await s.rollback()
        await s.execute(text("DELETE FROM release_eps WHERE symbol = 'ZZED'"))
        await s.commit()


def test_a_decimal_point_or_per_diluted_share_never_hides_a_diluted_figure():
    # COST: "Basic $ 6.76 Diluted $ 6.75" (a decimal point between "per share" and "Diluted" is not a sentence end)
    assert states_diluted_eps("NET INCOME PER COMMON SHARE ATTRIBUTABLE TO COSTCO: Basic $ 6.76 $ 6.01 Diluted $ 6.75 $ 5.99")
    # UDR, FE, C: "per diluted share" alone
    assert states_diluted_eps("Net income attributable to common stockholders was $0.21 per diluted share")
    assert states_diluted_eps("GAAP earnings of $0.50 per basic and diluted share")
    # a sentence end still separates "diluted" from an unrelated "per share"
    assert not states_diluted_eps("Shares were diluted by the offering. The dividend was $0.85 per share")
    assert not states_diluted_eps(ED)


def test_the_quarter_end_is_the_releases_own_never_a_prior_filings():
    # JPM 3Q26 (reported 2026-10-13): the narrative names only the prior 10-Q's quarter; that date is not this release's quarter
    jpm = ("For further information see pages 52-58 of the Firm's Quarterly Report on Form 10-Q for the quarterly period ended June 30, 2026. "
           "JPMorgan Chase reported third-quarter 2026 net income of $15.2 billion. Earnings per share - diluted $ 5.57 $ 7.70 $ 5.07")
    assert release_period_end(jpm, date(2026, 10, 13)) is None
    assert parse_release_eps(jpm, date(2026, 10, 13))["period_end"] is None
    # the supplement states it; the latest stated quarter end wins over a comparison period stated first
    supp = "Three months ended June 30, 2026 compared with three months ended September 30, 2026 and September 30, 2025"
    assert release_period_end(supp, date(2026, 10, 13)) == date(2026, 9, 30)
    from app.scripts.seed_release_eps import filing_period_end
    assert filing_period_end([("narrative.htm", jpm), ("supplement.htm", supp)], date(2026, 10, 13)) == date(2026, 9, 30)
    assert filing_period_end([("narrative.htm", jpm)], date(2026, 10, 13)) is None
    # an annual report reference is skipped too
    assert release_period_end("our Annual Report on Form 10-K for the quarter ended December 31, 2025", date(2026, 2, 1)) is None


def test_the_relabel_refuses_unless_the_release_states_no_diluted_eps_and_still_reads_the_figure():
    from app.scripts.relabel_release_eps_basis import UPDATE, refusal
    aep = "AEP reported second-quarter 2026 GAAP earnings of $702 million, or $1.31 per share, compared with $1.25 per share a year ago."
    row = {"eps_basis": "diluted", "diluted_eps_gaap": 1.31}
    assert refusal(None, aep, date(2026, 7, 30)) == "no stored row"
    assert refusal({**row, "eps_basis": "basic"}, aep, date(2026, 7, 30)) == "already stored as basic"
    assert refusal(row, None, date(2026, 7, 30)) == "the stored exhibit could not be read"
    assert refusal(row, aep + " Diluted earnings per share were $1.30.", date(2026, 7, 30)) == "the release states diluted EPS: the stored figure stays diluted"
    assert refusal({**row, "diluted_eps_gaap": 1.30}, aep, date(2026, 7, 30)).startswith("the release no longer reads as the stored figure")
    assert refusal(row, aep, date(2026, 7, 30)) is None
    assert "eps_basis = 'diluted'" in UPDATE and "basic_eps_gaap = diluted_eps_gaap, diluted_eps_gaap = NULL, eps_basis = 'basic'" in UPDATE
