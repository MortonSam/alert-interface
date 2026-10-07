"""Corporate actions read from 8-K Item 2.01 text: spin-offs by defined terms, the counterparty from "<Name> Common Stock", a
filing that only points to Item 8.01, a cash deal as other, and the issuer's own stock never taken as the counterparty."""
from datetime import date

from app.services.corporate_filings import classify_item_201

DD = ("Item 2.01 Completion of Material Acquisition or Disposition of Assets. On November 1, 2025, the Company effected the Distribution and completed the Separation. "
      "Qnity Common Stock will commence regular way trading on the New York Stock Exchange under the symbol Q on November 3, 2025. The stockholders of record of the Company "
      "received one (1) share of Qnity Common Stock for every two (2) shares of Company Common Stock. Item 9.01 Financial Statements and Exhibits.")
FDX = ("Item 2.01 Completion of Acquisition or Disposition of Assets. Immediately prior to the consummation of the Spin-Off, FedEx Freight was a wholly owned subsidiary of the Company. "
       "Effective as of 12:01 a.m., Central Time, on June 1, 2026, the Company completed the Spin-Off through the distribution by FedEx of 80.1% of the outstanding shares of FedEx Freight "
       "common stock on a pro rata basis to the holders of FedEx common stock. Item 9.01 Exhibits.")
SPGI = ("Item 2.01. Completion of Acquisition or Disposition of Assets. On the Distribution Date, S&P Global completed the previously-announced separation of Mobility Global. Effective as of "
        "12:01 a.m. New York City time on July 2, 2026, the common stock of Mobility Global was distributed, on a pro rata basis, to S&P Global's stockholders. Item 7.01 Regulation FD.")
HON = ("Item 2.01 Completion of Material Acquisition or Disposition of Assets. The information set forth in Item 8.01 is incorporated herein by reference. Item 8.01 Other Events. "
       "On June 29, 2026, Honeywell International Inc. completed the previously announced spin-off of Solstice Advanced Materials, Inc. through a pro rata distribution of all of the "
       "outstanding shares of Solstice Advanced Materials common stock to Honeywell shareowners. Item 9.01.")
CASH = ("Item 2.01 Completion of Acquisition or Disposition of Assets. On March 3, 2026, the Company completed its previously announced acquisition of Acme Robotics, Inc. for "
        "$2.1 billion in cash, pursuant to the Agreement and Plan of Merger. Item 9.01.")
STOCK = ("Item 2.01 Completion of Acquisition or Disposition of Assets. On May 5, 2026, Beta Corp completed the previously announced acquisition of Gamma Holdings, Inc. At the effective "
         "time, each share of Gamma common stock was converted into the right to receive 0.75 shares of Beta Corp common stock (the exchange ratio). Item 9.01.")


def test_spin_offs_by_defined_terms_with_the_counterparty_from_its_common_stock():
    c = classify_item_201(DD, date(2025, 11, 3), "DuPont de Nemours, Inc.")
    assert (c["kind"], c["date"], c["name"]) == ("spin_off", date(2025, 11, 1), "Qnity")
    c = classify_item_201(FDX, date(2026, 6, 1), "FedEx Corporation")
    assert (c["kind"], c["date"], c["name"]) == ("spin_off", date(2026, 6, 1), "FedEx Freight")      # not "FedEx common stock"
    c = classify_item_201(SPGI, date(2026, 7, 2), "S&P Global Inc.")
    assert (c["kind"], c["name"]) == ("spin_off", "Mobility Global")


def test_a_reference_to_item_801_reads_the_whole_filing():
    c = classify_item_201(HON, date(2026, 6, 29), "Honeywell International Inc.")
    assert (c["kind"], c["date"], c["name"]) == ("spin_off", date(2026, 6, 29), "Solstice Advanced Materials, Inc.")


def test_cash_deals_are_other_and_stock_deals_are_acquisitions():
    assert classify_item_201(CASH, date(2026, 3, 3), "Acme Corp")["kind"] == "other"
    c = classify_item_201(STOCK, date(2026, 5, 5), "Beta Corp")
    assert (c["kind"], c["name"]) == ("acquisition", "Gamma Holdings, Inc.")
    assert classify_item_201("Item 8.01 Other Events. Nothing here.", date(2026, 1, 1), "X") is None


def test_a_defined_term_is_not_a_counterparty_name():
    text = ("Item 2.01 Completion of Acquisition or Disposition of Assets. On February 9, 2026, the Company completed the previously announced spin-off of SpinCo through "
            "a pro rata distribution of all of the outstanding shares of SpinCo common stock. Item 9.01.")
    c = classify_item_201(text, date(2026, 2, 9), "Waters Corporation")
    assert c["kind"] == "spin_off" and c["name"] is None
