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


WAT = ("Introductory Note. On February 9, 2026 (the Closing Date), Waters Corporation, a Delaware corporation (Waters), and Becton, Dickinson and Company, a New Jersey corporation (BD), "
       "announced that they consummated the previously announced spin-off of BD's Biosciences and Diagnostic Solutions business (the SpinCo Business) and combination of the SpinCo "
       "Business with Waters. BD distributed, on a pro rata basis (the Distribution), one share of SpinCo common stock to each holder of BD common stock as of the Record Date, and following the "
       "Distribution, Merger Sub merged with and into SpinCo, and each share of SpinCo Common Stock was converted into the right to receive 0.135343148384084 shares of common stock of Waters. "
       "Item 2.01 Completion of Acquisition or Disposition of Assets. The information set forth in the Introductory Note is incorporated herein by reference. Item 9.01.")
WBD = ("Item 2.01 Completion of Acquisition or Disposition of Assets. The information set forth in the Introductory Note is incorporated by reference into this Item 2.01. Pursuant to the "
       "Merger Agreement, each share of WBD's Series A common stock, par value $0.01 per share (WBD Common Stock), issued and outstanding immediately prior to the effective time of the Merger "
       "was automatically canceled and converted into the right to receive an amount in cash equal to $31.01666668, without interest. Item 3.01 Notice of Delisting.")


def test_a_reverse_morris_trust_makes_the_filer_the_acquirer_and_names_the_spinner():
    c = classify_item_201(WAT, date(2026, 2, 9), "Waters Corporation")
    assert c["kind"] == "acquisition" and c["date"] == date(2026, 2, 9)
    assert c["name"] == "Becton, Dickinson and Company (Biosciences and Diagnostic Solutions)" and c["spinner"] == "Becton, Dickinson and Company" and c["spinner_kind"] == "spin_off"


def test_a_filer_bought_for_cash_is_other_not_a_merger():
    c = classify_item_201(WBD, date(2026, 10, 6), "Warner Bros. Discovery, Inc.")
    assert c["kind"] == "other"
