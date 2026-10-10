"""Permanent regression cases for the Discover headline guard: every headline reviewed in the rounds of 2026-10-10, with its verdicts.
Each row: (symbol, stored name, the change the page prints beside it (%), headline, guard verdict, may sit in the mover slot (as from a
source outside the established list), is a roundup). The guard verdict is None (may show), "number" (a stated percent more than 1.5
points from, or of the other sign than, the printed figure), "opposite_sign", "verb_up_on_down" or "verb_down_on_up". A headline the
guard suppresses shows nowhere; one that may not sit in the mover slot may still appear in In the news; a roundup shows nowhere.
To change a verdict, change the rule and this table together, with the reason in the commit."""
import pytest

from app.services import headline_guard as G
from app.services.news import is_roundup, mover_slot_ok, name_forms

KINDS = {"number": "it states", "opposite_sign": "its stated move has the opposite sign",
         "verb_up_on_down": "its verb says up on a down day", "verb_down_on_up": "its verb says down on an up day"}

CASES = [
    ('SBAC', 'SBA Communications Corporation', 7.34, "Why SBA Communications (SBAC) Is Up 15.1% After SpaceX’s $8 Billion Spectrum Deal - And What's Next", 'number', True, False),
    ('SBAC', 'SBA Communications Corporation', 7.34, 'SBA Communications (SBAC) Stock May Be Reasonable Despite Cash Flow Upside', None, False, False),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, 'T-Mobile Shares Fall 6.9% as SpaceX Spectrum Acquisition Raises Competition Concerns', 'number', True, False),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, 'Why T-Mobile Stock Just Crashed', None, False, False),
    ('TMUS', 'T-Mobile US, Inc.', 2.18, "Elon Musk Gets 'Very Big Deal' for SpaceX: Why AT&T, Verizon, T-Mobile Stocks are Falling", 'verb_down_on_up', True, True),
    ('CPAY', 'Corpay, Inc.', -0.09, "CPAY Stock Rises 14.6% in Three Months: Here's What You Should Know", None, False, False),
    ('META', 'Meta Platforms, Inc.', -0.41, 'Meta Stock Up 21% in One Month: New Movie About ‘Antihero’ Mark Zuckerberg Could Hurt Momentum', None, False, False),
    ('GS', 'The Goldman Sachs Group, Inc.', 0.42, 'Goldman Sachs Falls 20% From Record High and Enters Into Bears Market. How to Play GS Stock Here', None, False, False),
    ('HD', 'The Home Depot, Inc.', 1.97, 'Jim Cramer Sees Little Relief for Home Depot (HD) Until Rates Fall', None, True, False),
    ('PEP', 'PepsiCo, Inc. Common Stock', 3.73, 'PepsiCo Admits Its Soda Business Is Falling Behind Rivals', None, True, False),
    ('MU', 'Micron Technology, Inc.', -4.79, 'Why Micron (MU) Might be Well Poised for a Surge', None, False, False),
    ('VICI', 'VICI Properties Inc.', 0.66, 'VICI Properties (VICI) Stock Looks Discounted Despite Its 23% Slide', None, True, False),
    ('MU', 'Micron Technology, Inc.', 4.06, 'Micron shares fall as Taiwan workers authorize strike amid bonus dispute', 'verb_down_on_up', True, False),
    ('MU', 'Micron Technology, Inc.', 4.06, 'MU Stock Slides For Fourth Day: Taiwan Union Reportedly Secures Strike Authorization Over Bonus', 'verb_down_on_up', True, False),
    ('HUM', 'Humana Inc.', -2.37, 'Humana Soars On Medicare Advantage Star Rating', 'verb_up_on_down', True, False),
    ('HUM', 'Humana Inc.', -2.37, 'Humana Stock Surges After Key Medicare Advantage Plan Gets Higher Rating', 'verb_up_on_down', True, False),
    ('STZ', 'Constellation Brands, Inc.', 2.08, 'Constellation Brands stock falls as FY27 guidance disappoints', 'verb_down_on_up', True, False),
    ('STZ', 'Constellation Brands, Inc.', 2.08, 'STZ Stock Falls As Modelo And Corona Lose Volume, Full-Year Profit Outlook Holds', 'verb_down_on_up', True, False),
    ('TSLA', 'Tesla, Inc.', -0.74, 'Why Tesla (TSLA) Is Up 6.7% After Unveiling Terafab AI Chip Complex And Major New Credit Lines', 'opposite_sign', False, False),
    ('CRWD', 'CrowdStrike Holdings, Inc.', -4.81, 'Why NVDA, AMD, CRWD Stocks Surged To 52-Week Highs Today', 'verb_up_on_down', False, True),
    ('INTC', 'Intel Corporation', -5.34, 'Intel Stock Is Up 212% Since December. Here’s What Needs to Happen for Another 300% Long-Term Upside', None, False, False),
    ('INTC', 'Intel Corporation', -2.22, 'Intel Is Worth More Than Coca-Cola and PepsiCo Put Together', None, False, True),
    ('INTC', 'Intel Corporation', -5.34, 'Intel Slides 3% as Chip Stocks Sell Off With Yields and Oil Higher; NVIDIA and AMD Slip', 'number', True, True),
    ('INTC', 'Intel Corporation', -2.22, 'Intel Stock Fell 5% in a Day as Chip Stocks Sold Off Ahead of Its October 29 Report. Here’s Where the Stock Could Go', 'number', True, False),
    ('MRNA', 'Moderna, Inc.', -7.75, "NVAX, EBS, ARCT, MRNA Rally After Russia Plague Lab Worker's Death: Retail Traders Eye 'Contrac", 'verb_up_on_down', True, True),
    ('AMAT', 'Applied Materials, Inc.', -2.21, 'Applied Materials (AMAT) Is Up 11.4% After New AI Chip Memory and Packaging Partnerships Announced', 'opposite_sign', True, False),
    ('MRNA', 'Moderna, Inc.', 4.81, 'Novavax and Moderna Shares Fall as Citi Assesses Vaccine Sector Volatility', 'verb_down_on_up', True, False),
    ('HOOD', 'Robinhood Markets, Inc.', -2.22, 'Robinhood Rallies on a Framework Its Stock Tokens Can’t Use', 'verb_up_on_down', True, False),
    ('MRVL', 'Marvell Technology, Inc.', -0.81, 'Marvell Technology Stock Surges After Massive Long-Term Revenue Forecasts', 'verb_up_on_down', True, False),
    ('CMG', 'Chipotle Mexican Grill, Inc.', 6.21, 'Starbucks Slides 3% as Chipotle Mexican Grill Jumps 5% on Takeover Talk', None, True, False),
    ('CME', 'CME Group Inc.', 2.28, 'CME Group (CME) Adds Climate Linked Futures As International Volume Jumps 22%', None, True, False),
    ('AMT', 'American Tower Corporation', 9.3, 'American Tower (AMT) Stock May Be 43% Undervalued Despite Dividend Focus', None, False, False),
    ('AMT', 'American Tower Corporation', 9.3, 'Why American Tower Stock Jumped 8.6% Today', None, True, False),
    ('HUM', 'Humana Inc.', 11.56, 'Humana (HUM) Stock Trades Up, Here Is Why', None, False, False),
    ('HUM', 'Humana Inc.', 11.56, 'Humana Shares Surge Following Significant Medicare Advantage Star Ratings Improvement', None, True, False),
    ('HPQ', 'HP Inc.', -6.91, 'HP (HPQ) Stock Drops Despite Market Gains: Important Facts to Note', None, False, False),
    ('CCI', 'Crown Castle Inc.', 15.6, 'Why Crown Castle Stock Soared Today', None, True, False),
    ('T', 'AT&T Inc.', -10.82, 'Stock Market Today, Oct. 9: AT&T Slides on SpaceX Spectrum Deal Threat', None, True, False),
    ('VZ', 'Verizon Communications Inc.', -10.14, 'Verizon stock heads for worst day since 2002 as SpaceX U.S. network plans whack telcos', None, True, False),
    ('CCI', 'Crown Castle Inc.', 15.6, 'Crown Castle Soars 13% as SpaceX’s $8 Billion Spectrum Buy Keeps Tower Build Option “Very Much Alive”', 'number', True, False),
    ('SBAC', 'SBA Communications Corporation', 7.34, 'SBA Communications (SBAC) Jumped, But What Is Driving Attention Now?', None, True, False),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, 'Verizon, AT&T, T-Mobile Stocks Slide as SpaceX Expands Wireless Ambitions', None, True, True),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, 'Stocks making the biggest moves midday: T-Mobile, Verizon, AT&T, Crown Castle, Teva & more', None, True, True),
    ('MRNA', 'Moderna, Inc.', 14.21, 'Novavax Soars 16%, Moderna Surges 11%, Merck Climbs 3% as Biotech Rallies', 'number', True, True),
    ('MRNA', 'Moderna, Inc.', 14.21, 'BNTX, NVAX, MRNA Lead Vaccine Rally After Report Of An NIH Cancer-Vaccine Push', None, True, True),
    ('MRNA', 'Moderna, Inc.', 14.21, 'Why Moderna Stock Surged Today', None, True, False),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, 'T-Mobile’s partnership with Starlink hits unexpected turbulence', None, True, False),
    ('MRNA', 'Moderna, Inc.', 14.21, 'MRNA Stock Sets New 52-Week High As Nasdaq-100 Reentry Meets NIH Cancer-Vaccine Push', None, True, False),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, 'T-Mobile (TMUS): Expanding Market Share with Industry-Leading Cost Efficiency', None, True, False),
    ('HUM', 'Humana Inc.', 11.56, 'Humana Leads Managed Care Peers in 2027 Medicare Advantage Star Ratings, Deutsche Bank Says', None, True, False),
    ('T', 'AT&T Inc.', -10.82, 'Musk: Starlink Mobile V2 Brings “100 Times the Bandwidth,” Raising the Stakes for Verizon and AT&T', None, True, False),
    ('VZ', 'Verizon Communications Inc.', -10.14, 'Stock Market Today, Oct. 9: Verizon Slides on SpaceX Spectrum Deal and Scotiabank Target Cut', None, True, False),
    ('DDOG', 'Datadog, Inc.', 7.11, 'Datadog (DDOG): Capitalizing on AI-Native Adoption and Cloud Observability Demand', None, True, False),
    ('CIEN', 'Ciena Corporation', 5.6, 'Jim Cramer Likes Ciena (CIEN) but Another Optical Stock Holds His Attention', None, True, False),
    ('DDOG', 'Datadog, Inc.', 7.11, 'Fastly Spikes 15% as Oppenheimer Upgrades to Outperform With $35 Target; Datadog Rises 4%, Cloudflare Gains 2%', 'number', True, False),
]
UNIVERSE = {sym: name for sym, name, *_ in CASES}
UNIVERSE.update({"NVDA": "NVIDIA Corporation", "AMD": "Advanced Micro Devices, Inc.", "KO": "The Coca-Cola Company", "MRK": "Merck & Co., Inc.",
                 "SBUX": "Starbucks Corporation"})


@pytest.mark.parametrize("sym,name,printed,headline,verdict,slot,roundup", CASES, ids=[f"{c[0]}:{c[3][:40]}" for c in CASES])
def test_headline_verdict(sym, name, printed, headline, verdict, slot, roundup):
    forms = name_forms(sym, name)
    reason = G.check(headline, printed, forms).reason
    assert (reason is None) if verdict is None else (reason or "").startswith(KINDS[verdict]), reason
    assert mover_slot_ok(headline, "Yahoo", printed, forms) == slot
    assert is_roundup(headline, UNIVERSE) == roundup
