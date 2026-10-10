"""Permanent regression cases for the Discover headline guard: every headline from the review rounds of 2026-10-10 with its verdict.
Each row: (symbol, stored name, our close-to-close move %, published after the close, headline, guard verdict, may sit in the mover slot).
The guard verdict is None (may show), "opposite_sign", "after_close", "verb_up_on_down" or "verb_down_on_up". A headline the guard
suppresses shows nowhere; one that may not sit in the mover slot may still appear in In the news.
To change a verdict, change the rule and this table together, with the reason in the commit."""
import pytest

from app.services import headline_guard as G
from app.services.news import mover_slot_ok, name_forms

KINDS = {"opposite_sign": "its stated move has the opposite sign", "after_close": "published after the close",
         "verb_up_on_down": "its verb says up on a down day", "verb_down_on_up": "its verb says down on an up day"}

CASES = [
    ('SBAC', 'SBA Communications Corporation', 7.34, True, "Why SBA Communications (SBAC) Is Up 15.1% After SpaceX’s $8 Billion Spectrum Deal - And What's Next", 'after_close', True),
    ('SBAC', 'SBA Communications Corporation', 7.34, False, 'SBA Communications (SBAC) Stock May Be Reasonable Despite Cash Flow Upside', None, False),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, False, 'T-Mobile Shares Fall 6.9% as SpaceX Spectrum Acquisition Raises Competition Concerns', None, True),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, True, 'T-Mobile Shares Fall 6.9% as SpaceX Spectrum Acquisition Raises Competition Concerns', 'after_close', True),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, False, 'Why T-Mobile Stock Just Crashed', None, False),
    ('TMUS', 'T-Mobile US, Inc.', 2.18, False, "Elon Musk Gets 'Very Big Deal' for SpaceX: Why AT&T, Verizon, T-Mobile Stocks are Falling", 'verb_down_on_up', True),
    ('CPAY', 'Corpay, Inc.', -0.09, False, "CPAY Stock Rises 14.6% in Three Months: Here's What You Should Know", None, False),
    ('META', 'Meta Platforms, Inc.', -0.41, False, 'Meta Stock Up 21% in One Month: New Movie About ‘Antihero’ Mark Zuckerberg Could Hurt Momentum', None, False),
    ('GS', 'The Goldman Sachs Group, Inc.', 0.42, False, 'Goldman Sachs Falls 20% From Record High and Enters Into Bears Market. How to Play GS Stock Here', None, False),
    ('HD', 'The Home Depot, Inc.', 1.97, False, 'Jim Cramer Sees Little Relief for Home Depot (HD) Until Rates Fall', None, True),
    ('PEP', 'PepsiCo, Inc.', 3.73, False, 'PepsiCo Admits Its Soda Business Is Falling Behind Rivals', None, True),
    ('MU', 'Micron Technology, Inc.', -4.79, False, 'Why Micron (MU) Might be Well Poised for a Surge', None, False),
    ('VICI', 'VICI Properties Inc.', 0.66, False, 'VICI Properties (VICI) Stock Looks Discounted Despite Its 23% Slide', None, True),
    ('MU', 'Micron Technology, Inc.', 4.06, False, 'Micron shares fall as Taiwan workers authorize strike amid bonus dispute', 'verb_down_on_up', True),
    ('MU', 'Micron Technology, Inc.', 4.06, False, 'MU Stock Slides For Fourth Day: Taiwan Union Reportedly Secures Strike Authorization Over Bonus', 'verb_down_on_up', True),
    ('HUM', 'Humana Inc.', -2.37, False, 'Humana Soars On Medicare Advantage Star Rating', 'verb_up_on_down', True),
    ('HUM', 'Humana Inc.', -2.37, False, 'Humana Stock Surges After Key Medicare Advantage Plan Gets Higher Rating', 'verb_up_on_down', True),
    ('STZ', 'Constellation Brands, Inc.', 2.08, False, 'Constellation Brands stock falls as FY27 guidance disappoints', 'verb_down_on_up', True),
    ('STZ', 'Constellation Brands, Inc.', 2.08, False, 'STZ Stock Falls As Modelo And Corona Lose Volume, Full-Year Profit Outlook Holds', 'verb_down_on_up', True),
    ('TSLA', 'Tesla, Inc.', -0.74, False, 'Why Tesla (TSLA) Is Up 6.7% After Unveiling Terafab AI Chip Complex And Major New Credit Lines', 'opposite_sign', False),
    ('CRWD', 'CrowdStrike Holdings, Inc.', -4.81, False, 'Why NVDA, AMD, CRWD Stocks Surged To 52-Week Highs Today', 'verb_up_on_down', False),
    ('INTC', 'Intel Corporation', -5.34, False, 'Intel Stock Is Up 212% Since December. Here’s What Needs to Happen for Another 300% Long-Term Upside', None, False),
    ('INTC', 'Intel Corporation', -2.22, False, 'Intel Is Worth More Than Coca-Cola and PepsiCo Put Together', None, False),
    ('INTC', 'Intel Corporation', -5.34, False, 'Intel Slides 3% as Chip Stocks Sell Off With Yields and Oil Higher; NVIDIA and AMD Slip', None, True),
    ('INTC', 'Intel Corporation', -2.22, False, 'Intel Stock Fell 5% in a Day as Chip Stocks Sold Off Ahead of Its October 29 Report. Here’s Where the Stock Could Go', None, False),
    ('MRNA', 'Moderna, Inc.', -7.75, False, "NVAX, EBS, ARCT, MRNA Rally After Russia Plague Lab Worker's Death: Retail Traders Eye 'Contrac", 'verb_up_on_down', True),
    ('AMAT', 'Applied Materials, Inc.', -2.21, False, 'Applied Materials (AMAT) Is Up 11.4% After New AI Chip Memory and Packaging Partnerships Announced', 'opposite_sign', True),
    ('MRNA', 'Moderna, Inc.', 4.81, False, 'Novavax and Moderna Shares Fall as Citi Assesses Vaccine Sector Volatility', 'verb_down_on_up', True),
    ('HOOD', 'Robinhood Markets, Inc.', -2.22, False, 'Robinhood Rallies on a Framework Its Stock Tokens Can’t Use', 'verb_up_on_down', True),
    ('MRVL', 'Marvell Technology, Inc.', -0.81, False, 'Marvell Technology Stock Surges After Massive Long-Term Revenue Forecasts', 'verb_up_on_down', True),
    ('CMG', 'Chipotle Mexican Grill, Inc.', 6.21, False, 'Starbucks Slides 3% as Chipotle Mexican Grill Jumps 5% on Takeover Talk', None, True),
    ('CME', 'CME Group Inc.', 2.28, False, 'CME Group (CME) Adds Climate Linked Futures As International Volume Jumps 22%', None, True),
    ('AMT', 'American Tower Corporation', 9.3, False, 'American Tower (AMT) Stock May Be 43% Undervalued Despite Dividend Focus', None, False),
    ('AMT', 'American Tower Corporation', 9.3, False, 'Why American Tower Stock Jumped 8.6% Today', None, True),
    ('HUM', 'Humana Inc.', 11.56, True, 'Humana (HUM) Stock Trades Up, Here Is Why', None, False),
    ('HUM', 'Humana Inc.', 11.56, False, 'Humana Shares Surge Following Significant Medicare Advantage Star Ratings Improvement', None, True),
    ('HPQ', 'HP Inc.', -6.91, True, 'HP (HPQ) Stock Drops Despite Market Gains: Important Facts to Note', None, False),
    ('CCI', 'Crown Castle Inc.', 15.6, False, 'Why Crown Castle Stock Soared Today', None, True),
    ('T', 'AT&T Inc.', -10.82, True, 'Stock Market Today, Oct. 9: AT&T Slides on SpaceX Spectrum Deal Threat', None, True),
    ('VZ', 'Verizon Communications Inc.', -10.14, False, 'Verizon stock heads for worst day since 2002 as SpaceX U.S. network plans whack telcos', None, True),
]


@pytest.mark.parametrize("sym,name,move,after,headline,verdict,slot", CASES, ids=[f"{c[0]}:{c[4][:40]}" for c in CASES])
def test_headline_verdict(sym, name, move, after, headline, verdict, slot):
    forms = name_forms(sym, name)
    reason = G.check(headline, move, forms, after_close=after).reason
    assert (reason is None) if verdict is None else (reason or "").startswith(KINDS[verdict]), reason
    assert mover_slot_ok(headline, "Yahoo", move, forms) == slot          # as from a source outside the established list
