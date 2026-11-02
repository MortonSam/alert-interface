"""A research note is written again after a material 8-K (Sam, 2026-11-02): services/material_filings and the nightly queue."""
from datetime import datetime, timezone

import pytest

from app.services import material_filings as M


@pytest.mark.parametrize("items,material", [
    ("1.01,9.01", True), ("1.02", True), ("2.01,9.01", True), ("2.05", True), ("2.06", True), ("5.01", True),
    ("5.02,9.01", False),            # only with its words: leadership_change
    ("2.02,9.01", False),            # results: the earnings report rule covers them
    ("5.07", False), ("3.02", False),
])
def test_the_always_material_items(items, material):
    assert M.verdict({"items": items}, None)[0] is material


def test_a_7_01_or_8_01_filing_is_material_only_when_its_words_announce_guidance_a_deal_or_a_legal_matter():
    rec = {"items": "7.01,9.01"}
    assert M.needs_text(rec)
    assert M.verdict(rec, "The Company raised its full-year 2026 guidance for revenue.") == (True, ["guidance"])
    assert M.verdict({"items": "8.01"}, "The Company entered into a definitive merger agreement with Acme Corp.") == (True, ["deal"])
    assert M.verdict({"items": "8.01"}, "The parties entered into a settlement agreement resolving the class action.") == (True, ["legal"])
    assert M.verdict({"items": "8.01"}, "The Board declared a quarterly dividend of $0.25 per share.") == (False, [])
    assert M.verdict(rec, "The Company will present at the investor conference on November 12.") == (False, [])
    assert not M.needs_text({"items": "1.01,8.01"})          # always material: no need to read it to decide
    # an earnings release with its outlook under 7.01 is the report itself: the report rule writes the note again
    assert M.verdict({"items": "2.02,7.01,9.01"}, "The Company raised its full-year 2026 guidance.") == (False, [])
    assert not M.needs_text({"items": "2.02,7.01,9.01"})
    assert M.verdict({"items": "2.02,5.02,9.01"}, "Item 5.02. Jane Roe will retire as Chief Financial Officer on March 31.") == (True, ["Item 5.02"])


TITLE = ("Item 5.02 Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers; "
         "Compensatory Arrangements of Certain Officers. ")


@pytest.mark.parametrize("body", [
    "On October 28, 2026, John Smith informed the Board that he will resign as Chief Executive Officer, effective December 31.",
    "The Board appointed Maria Lopez as Chief Financial Officer, effective November 15, 2026.",
    "The Board elected Ann Lee to serve as a director, increasing its size to twelve members.",
    "Mr. Brown will retire from his role as Chairman of the Board at the 2027 annual meeting.",
    "The Company named Raj Patel President and Chief Operating Officer.",
    # the scan's own cases (2026-11-02): an abbreviation or an initial inside the sentence
    "On July 16, 2026, Kara Wilson notified the Board of Directors (the Board) of Paychex, Inc. (the Company) of her decision not to stand for re-election.",
    "On July 20, 2026, the Board of Directors of the Company elected David S. Marriott and Charles J. Meyers to serve as directors.",
    "On September 29, 2026, the Board of Directors of Roper Technologies, Inc. elected Mr. Abhijit Dubey to serve as a member of the Board.",
    "On August 17, 2026, Aon plc announced that Edmund Reese will transition from his role as Executive Vice President and Chief Financial Officer.",
])
def test_item_5_02_counts_when_it_announces_a_leadership_change(body):
    assert M.leadership_change(TITLE + body)
    assert M.verdict({"items": "5.02,9.01"}, TITLE + body) == (True, ["Item 5.02"])
    assert M.needs_text({"items": "5.02,9.01"})


@pytest.mark.parametrize("body", [
    "The Compensation Committee approved an amendment to the 2020 Omnibus Incentive Plan to increase the shares reserved.",
    "The Company entered into an amended and restated severance agreement with its Chief Executive Officer.",
    "The Board approved the annual base salaries and target bonus opportunities of the named executive officers for 2027.",
    "The Company adopted the Executive Officer Clawback Policy, effective December 1, 2026.",
    # officers outside the list: a vice president, a chief administrative or legal officer
    "Mr. Keenan will step down as Chief Administrative Officer but will continue to serve as Senior Executive Vice President of the Company.",
    "Benjamin Lee notified Reddit of his intention to step down as Chief Legal Officer and Corporate Secretary.",
])
def test_item_5_02_that_only_sets_or_amends_pay_or_plans_does_not_count(body):
    assert not M.leadership_change(TITLE + body)
    assert M.verdict({"items": "5.02,9.01"}, TITLE + body) == (False, [])


def test_the_excerpt_is_the_filings_own_items_then_its_exhibit():
    cover = "FORM 8-K header text Item 5.02 Departure of Directors. Jane Roe resigned as Chief Financial Officer. SIGNATURES Pursuant to"
    ex = "Exhibit 99.1 Press release: the company named John Doe interim CFO."
    out = M.excerpt([("cover.htm", cover), ("ex99.htm", ex)])
    assert out.startswith("Item 5.02") and "SIGNATURES" not in out and "John Doe interim CFO" in out
    assert len(M.excerpt([("c", "Item 1.01 " + "x " * 5000)])) == M.EXCERPT_CHARS


def test_pending_and_the_prompt_block_follow_the_note_and_its_filing():
    rows = [{"accession": "a1", "filed_on": "2026-11-02", "acceptance": "2026-11-02T16:30:00.000Z", "items": "5.02", "material": True,
             "why": ["Item 5.02"], "url": "u1", "excerpt": "Item 5.02 CFO resigned."},
            {"accession": "a0", "filed_on": "2026-10-20", "acceptance": "2026-10-20T16:30:00.000Z", "items": "8.01", "material": False,
             "why": [], "url": "u0", "excerpt": None}]
    written = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
    assert [r["accession"] for r in M.newer_than(rows, written)] == ["a1"]
    assert M.newer_than(rows, datetime(2026, 11, 3, tzinfo=timezone.utc)) == []


@pytest.mark.asyncio
async def test_pending_for_and_prompt_block_read_the_stored_list(monkeypatch):
    rows = [{"accession": "a1", "filed_on": "2026-11-02", "acceptance": "2026-11-02T16:30:00.000Z", "items": "5.02", "material": True,
             "why": ["Item 5.02"], "url": "u1", "excerpt": "Item 5.02 CFO resigned."}]

    async def stored(db, symbol):
        return rows
    monkeypatch.setattr(M, "stored", stored)
    p = await M.pending_for(None, "ZZMF", datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert p == {"form": "8-K", "items": "5.02", "why": ["Item 5.02"], "filed_on": "2026-11-02", "url": "u1"}
    assert await M.pending_for(None, "ZZMF", datetime(2026, 11, 3, tzinfo=timezone.utc)) is None
    block = await M.prompt_block(None, "ZZMF", "2026-10-30")
    assert "8-K filed 2026-11-02 (Item 5.02)" in block and "CFO resigned" in block
    assert await M.prompt_block(None, "ZZMF", "2026-11-05") is None                       # filed before the 10-Q the note rests on
    assert await M.prompt_block(None, "ZZMF", "2026-10-30", before=datetime(2026, 11, 1, tzinfo=timezone.utc)) is None   # after the note


def test_the_queue_writes_a_note_after_a_material_filing_and_then_every_note_under_the_old_rule_largest_first():
    from app.scripts.generate_notes import due_kind, queue
    assert due_kind("complete", True, 2) == (3, "write")                     # a report or a material 8-K since the note
    assert due_kind("complete", False, 2, old_rule=True) == (4, "write")     # written before the live-figure rule
    assert due_kind("complete", False, 2) is None
    rows = [("SMALL", "complete", False, 2, 1e9, False, False, True), ("BIG", "complete", False, 2, 5e12, False, False, True),
            ("FILED", "complete", True, 2, 2e9, False, False, False), ("NEW", None, False, None, 1e10, False, False, False),
            ("DONE", "complete", False, 2, 9e12, False, False, False)]
    assert queue(rows, 10) == ["NEW", "FILED", "BIG", "SMALL"]
