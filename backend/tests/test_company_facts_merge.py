"""compute_pe merges company facts only from a ticker's named predecessor CIKs, never from the CIK in an accession prefix (the
submitter, often a filing agent: Workiva Inc. files for its clients under its own CIK and its quarters leaked into fifty tickers)."""
import pytest

from app.scripts.compute_pe import company_facts_merged
from app.services.edgar_client import PREDECESSOR_CIKS


def _facts(entity, series):
    return {"entityName": entity, "facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": series}}}}}


class FakeEdgar:
    def __init__(self):
        self.calls = []
        self.data = {
            "0000909832": _facts("COSTCO", [{"accn": "0000909832-26-000084", "end": "2026-08-30", "val": 6.75}, {"accn": "0001445305-26-000011", "end": "2026-05-10", "val": 4.93}]),
            "0001445305": _facts("WORKIVA INC", [{"accn": "0001445305-26-000011", "end": "2026-03-31", "val": 0.33}]),
            "0002041610": _facts("Paramount Skydance", [{"accn": "0002041610-26-000003", "end": "2026-06-30", "val": 0.10}]),
            "0000813828": _facts("Paramount Global", [{"accn": "0000813828-25-000030", "end": "2025-03-31", "val": 0.22}]),
        }
    async def get_company_facts(self, cik):
        self.calls.append(cik)
        return self.data[cik]


@pytest.mark.asyncio
async def test_the_filing_agents_cik_is_never_merged_and_a_predecessors_is():
    e = FakeEdgar()
    f = await company_facts_merged(e, "0000909832", "COST")
    vals = [x["val"] for x in f["facts"]["us-gaap"]["EarningsPerShareDiluted"]["units"]["USD/shares"]]
    assert vals == [6.75, 4.93] and e.calls == ["0000909832"]                          # Workiva's accession prefix fetches nothing
    e = FakeEdgar()
    f = await company_facts_merged(e, "0002041610", "SKYD")
    vals = [x["val"] for x in f["facts"]["us-gaap"]["EarningsPerShareDiluted"]["units"]["USD/shares"]]
    assert vals == [0.10, 0.22] and e.calls == ["0002041610", "0000813828"]              # the named predecessor is merged
    assert PREDECESSOR_CIKS["SKYD"] == ["0000813828", "0002041610"] and "PSKY" not in PREDECESSOR_CIKS
    from app.scripts.backfill_report_timing import CIK_OVERRIDES
    assert CIK_OVERRIDES is PREDECESSOR_CIKS
