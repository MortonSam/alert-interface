"""Permanent regression cases for the Discover headline guard: every headline reviewed in the rounds of 2026-10-10, with its verdicts.
Each row: (symbol, stored name, the change the page prints beside it (%), headline, guard verdict, may sit in the mover slot, is a
roundup, is opinion or promotion, explains a move, leads with the stock). The guard verdict is None (may show), "number" (a stated
percent more than 1.5 points from the printed figure), "opposite_sign", "verb_up_on_down", "verb_down_on_up" or "flat" (a flat word
beside a printed move of more than 2 points). A headline that does not name the stock in its first clause counts for it nowhere. A headline the guard suppresses shows
nowhere; one that may not sit in the mover slot (a contrary longer-period move) may still appear in In the news; a roundup and an
opinion headline show nowhere; an explainer ("Why X stock soared today") stays eligible and ranks as news when it agrees with the move.
To change a verdict, change the rule and this table together, with the reason in the commit."""
from datetime import date, datetime, timezone

import pytest

from app.services import headline_guard as G
from app.services.news import headline_problem, is_roundup, mover_slot_ok, name_forms

KINDS = {"number": "it states", "opposite_sign": "its stated move has the opposite sign",
         "verb_up_on_down": "its verb says up on a down day", "verb_down_on_up": "its verb says down on an up day", "flat": "its words say flat"}

CASES = [
    ('SBAC', 'SBA Communications Corporation', 7.34, "Why SBA Communications (SBAC) Is Up 15.1% After SpaceX’s $8 Billion Spectrum Deal - And What's Next", 'number', True, False, False, True, True),
    ('SBAC', 'SBA Communications Corporation', 7.34, 'SBA Communications (SBAC) Stock May Be Reasonable Despite Cash Flow Upside', None, True, False, True, False, True),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, 'T-Mobile Shares Fall 6.9% as SpaceX Spectrum Acquisition Raises Competition Concerns', 'number', True, False, False, False, True),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, 'Why T-Mobile Stock Just Crashed', None, True, False, False, True, True),
    ('TMUS', 'T-Mobile US, Inc.', 2.18, "Elon Musk Gets 'Very Big Deal' for SpaceX: Why AT&T, Verizon, T-Mobile Stocks are Falling", 'verb_down_on_up', True, False, False, False, False),
    ('CPAY', 'Corpay, Inc.', -0.09, "CPAY Stock Rises 14.6% in Three Months: Here's What You Should Know", None, False, False, True, False, True),
    ('META', 'Meta Platforms, Inc.', -0.41, 'Meta Stock Up 21% in One Month: New Movie About ‘Antihero’ Mark Zuckerberg Could Hurt Momentum', None, False, False, True, False, True),
    ('GS', 'The Goldman Sachs Group, Inc.', 0.42, 'Goldman Sachs Falls 20% From Record High and Enters Into Bears Market. How to Play GS Stock Here', None, False, False, False, False, True),
    ('HD', 'The Home Depot, Inc.', 1.97, 'Jim Cramer Sees Little Relief for Home Depot (HD) Until Rates Fall', None, True, False, True, False, True),
    ('PEP', 'PepsiCo, Inc. Common Stock', 3.73, 'PepsiCo Admits Its Soda Business Is Falling Behind Rivals', None, True, False, False, False, True),
    ('MU', 'Micron Technology, Inc.', -4.79, 'Why Micron (MU) Might be Well Poised for a Surge', None, True, False, True, True, True),
    ('VICI', 'VICI Properties Inc.', 0.66, 'VICI Properties (VICI) Stock Looks Discounted Despite Its 23% Slide', None, True, False, True, False, True),
    ('MU', 'Micron Technology, Inc.', 4.06, 'Micron shares fall as Taiwan workers authorize strike amid bonus dispute', 'verb_down_on_up', True, False, False, False, True),
    ('MU', 'Micron Technology, Inc.', 4.06, 'MU Stock Slides For Fourth Day: Taiwan Union Reportedly Secures Strike Authorization Over Bonus', 'verb_down_on_up', True, False, False, False, True),
    ('HUM', 'Humana Inc.', -2.37, 'Humana Soars On Medicare Advantage Star Rating', 'verb_up_on_down', True, False, False, False, True),
    ('HUM', 'Humana Inc.', -2.37, 'Humana Stock Surges After Key Medicare Advantage Plan Gets Higher Rating', 'verb_up_on_down', True, False, False, False, True),
    ('STZ', 'Constellation Brands, Inc.', 2.08, 'Constellation Brands stock falls as FY27 guidance disappoints', 'verb_down_on_up', True, False, False, False, True),
    ('STZ', 'Constellation Brands, Inc.', 2.08, 'STZ Stock Falls As Modelo And Corona Lose Volume, Full-Year Profit Outlook Holds', 'verb_down_on_up', True, False, False, False, True),
    ('TSLA', 'Tesla, Inc.', -0.74, 'Why Tesla (TSLA) Is Up 6.7% After Unveiling Terafab AI Chip Complex And Major New Credit Lines', 'verb_up_on_down', True, False, False, True, True),
    ('CRWD', 'CrowdStrike Holdings, Inc.', -4.81, 'Why NVDA, AMD, CRWD Stocks Surged To 52-Week Highs Today', 'verb_up_on_down', True, False, False, True, True),
    ('INTC', 'Intel Corporation', -5.34, 'Intel Stock Is Up 212% Since December. Here’s What Needs to Happen for Another 300% Long-Term Upside', None, False, False, True, False, True),
    ('INTC', 'Intel Corporation', -2.22, 'Intel Is Worth More Than Coca-Cola and PepsiCo Put Together', None, True, False, True, False, True),
    ('INTC', 'Intel Corporation', -5.34, 'Intel Slides 3% as Chip Stocks Sell Off With Yields and Oil Higher; NVIDIA and AMD Slip', 'number', True, False, False, False, True),
    ('INTC', 'Intel Corporation', -2.22, 'Intel Stock Fell 5% in a Day as Chip Stocks Sold Off Ahead of Its October 29 Report. Here’s Where the Stock Could Go', 'number', True, False, True, False, True),
    ('MRNA', 'Moderna, Inc.', -7.75, "NVAX, EBS, ARCT, MRNA Rally After Russia Plague Lab Worker's Death: Retail Traders Eye 'Contrac", 'verb_up_on_down', True, False, False, False, True),
    ('AMAT', 'Applied Materials, Inc.', -2.21, 'Applied Materials (AMAT) Is Up 11.4% After New AI Chip Memory and Packaging Partnerships Announced', 'verb_up_on_down', True, False, False, False, True),
    ('MRNA', 'Moderna, Inc.', 4.81, 'Novavax and Moderna Shares Fall as Citi Assesses Vaccine Sector Volatility', 'verb_down_on_up', True, False, False, False, True),
    ('HOOD', 'Robinhood Markets, Inc.', -2.22, 'Robinhood Rallies on a Framework Its Stock Tokens Can’t Use', 'verb_up_on_down', True, False, False, False, True),
    ('MRVL', 'Marvell Technology, Inc.', -0.81, 'Marvell Technology Stock Surges After Massive Long-Term Revenue Forecasts', 'verb_up_on_down', True, False, False, False, True),
    ('CMG', 'Chipotle Mexican Grill, Inc.', 6.21, 'Starbucks Slides 3% as Chipotle Mexican Grill Jumps 5% on Takeover Talk', None, True, False, False, False, False),
    ('CME', 'CME Group Inc.', 2.28, 'CME Group (CME) Adds Climate Linked Futures As International Volume Jumps 22%', None, True, False, False, False, True),
    ('AMT', 'American Tower Corporation', 9.3, 'American Tower (AMT) Stock May Be 43% Undervalued Despite Dividend Focus', None, True, False, True, False, True),
    ('AMT', 'American Tower Corporation', 9.3, 'Why American Tower Stock Jumped 8.6% Today', None, True, False, False, True, True),
    ('HUM', 'Humana Inc.', 11.56, 'Humana (HUM) Stock Trades Up, Here Is Why', None, True, False, False, True, True),
    ('HUM', 'Humana Inc.', 11.56, 'Humana Shares Surge Following Significant Medicare Advantage Star Ratings Improvement', None, True, False, False, False, True),
    ('HPQ', 'HP Inc.', -6.91, 'HP (HPQ) Stock Drops Despite Market Gains: Important Facts to Note', None, True, False, True, False, True),
    ('CCI', 'Crown Castle Inc.', 15.6, 'Why Crown Castle Stock Soared Today', None, True, False, False, True, True),
    ('T', 'AT&T Inc.', -10.82, 'Stock Market Today, Oct. 9: AT&T Slides on SpaceX Spectrum Deal Threat', None, True, False, False, False, True),
    ('VZ', 'Verizon Communications Inc.', -10.14, 'Verizon stock heads for worst day since 2002 as SpaceX U.S. network plans whack telcos', None, True, False, False, False, True),
    ('CCI', 'Crown Castle Inc.', 15.6, 'Crown Castle Soars 13% as SpaceX’s $8 Billion Spectrum Buy Keeps Tower Build Option “Very Much Alive”', 'number', True, False, False, False, True),
    ('SBAC', 'SBA Communications Corporation', 7.34, 'SBA Communications (SBAC) Jumped, But What Is Driving Attention Now?', None, True, False, False, False, True),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, 'Verizon, AT&T, T-Mobile Stocks Slide as SpaceX Expands Wireless Ambitions', None, True, False, False, False, True),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, 'Stocks making the biggest moves midday: T-Mobile, Verizon, AT&T, Crown Castle, Teva & more', None, True, True, False, False, True),
    ('MRNA', 'Moderna, Inc.', 14.21, 'Novavax Soars 16%, Moderna Surges 11%, Merck Climbs 3% as Biotech Rallies', 'number', True, False, False, False, False),
    ('MRNA', 'Moderna, Inc.', 14.21, 'BNTX, NVAX, MRNA Lead Vaccine Rally After Report Of An NIH Cancer-Vaccine Push', None, True, False, False, False, True),
    ('MRNA', 'Moderna, Inc.', 14.21, 'Why Moderna Stock Surged Today', None, True, False, False, True, True),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, 'T-Mobile’s partnership with Starlink hits unexpected turbulence', None, True, False, False, False, True),
    ('MRNA', 'Moderna, Inc.', 14.21, 'MRNA Stock Sets New 52-Week High As Nasdaq-100 Reentry Meets NIH Cancer-Vaccine Push', None, True, False, False, False, True),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, 'T-Mobile (TMUS): Expanding Market Share with Industry-Leading Cost Efficiency', None, True, False, True, False, True),
    ('HUM', 'Humana Inc.', 11.56, 'Humana Leads Managed Care Peers in 2027 Medicare Advantage Star Ratings, Deutsche Bank Says', None, True, False, False, False, True),
    ('T', 'AT&T Inc.', -10.82, 'Musk: Starlink Mobile V2 Brings “100 Times the Bandwidth,” Raising the Stakes for Verizon and AT&T', None, True, False, False, False, False),
    ('VZ', 'Verizon Communications Inc.', -10.14, 'Stock Market Today, Oct. 9: Verizon Slides on SpaceX Spectrum Deal and Scotiabank Target Cut', None, True, False, False, False, True),
    ('DDOG', 'Datadog, Inc.', 7.11, 'Datadog (DDOG): Capitalizing on AI-Native Adoption and Cloud Observability Demand', None, True, False, True, False, True),
    ('CIEN', 'Ciena Corporation', 5.6, 'Jim Cramer Likes Ciena (CIEN) but Another Optical Stock Holds His Attention', None, True, False, True, False, True),
    ('DDOG', 'Datadog, Inc.', 7.11, 'Fastly Spikes 15% as Oppenheimer Upgrades to Outperform With $35 Target; Datadog Rises 4%, Cloudflare Gains 2%', 'number', True, False, False, False, False),
    ('TMUS', 'T-Mobile US, Inc.', -13.27, 'SpaceX snaps up the 800 MHz spectrum T-Mobile dumped for $2.9 billion — and T-Mobile, Verizon, AT&T stocks are sliding', None, True, False, False, False, True),
    ('HUM', 'Humana Inc.', 11.56, 'Stock Market Midday, Oct. 9: Stocks Edge Higher, Humana jumps 13%', None, True, False, False, False, False),
    ('DDOG', 'Datadog, Inc.', 7.11, 'Why Is Datadog (DDOG) Stock Soaring Today', None, True, False, False, True, True),
    ('SWKS', 'Skyworks Solutions, Inc.', -5.45, 'Apple Drops 3% on Reported iPhone 18 Pro Component Order Cuts; Skyworks Slips, Qualcomm Treads Water', None, True, False, False, False, False),
    ('LITE', 'Lumentum Holdings Inc.', 5.22, 'Lumentum Stock Jumps as CEO Reveals AI Optical Components Sold Out Through 2029', None, True, False, False, False, True),
    ('PLTR', 'Palantir Technologies Inc.', 5.17, 'Goldman Predicts a “Step Function Change” in Palantir’s AI Opportunity', None, True, False, False, False, True),
    ('PANW', 'Palo Alto Networks, Inc.', 5.09, 'Zscaler Jumps 6% on Reaffirmed Revenue Outlook and IBM Security Pact; Palo Alto and CrowdStrike Gain 4%', None, True, False, False, False, False),
    ('VZ', 'Verizon Communications Inc.', -10.14, 'Verizon Shares Fall 5.4% After SpaceX Spectrum Deal Raises Competition Concerns', 'number', True, False, False, False, True),
    ('T', 'AT&T Inc.', -10.82, 'SpaceX Climbs 4% on Nationwide Low-Band Spectrum Deal for Starlink Mobile; Verizon and AT&T Drop 7%', 'number', True, False, False, False, False),
    ('INTC', 'Intel Corporation', -3.1, 'Intel Slides 3% as Chip Stocks Sell Off With Yields and Oil Higher; NVIDIA and AMD Slip', None, True, False, False, False, True),
    ('NVDA', 'NVIDIA Corporation', -1.2, 'Intel Slides 3% as Chip Stocks Sell Off With Yields and Oil Higher; NVIDIA and AMD Slip', None, True, False, False, False, False),
    ('TMUS', 'T-Mobile US, Inc.', 2.18, 'Verizon, AT&T, T-Mobile Stocks Slide as SpaceX Expands Wireless Ambitions', 'verb_down_on_up', True, False, False, False, True),
    ('PLTR', 'Palantir Technologies Inc.', 5.17, 'Better High-Growth AI Stock: CrowdStrike vs. Palantir Technologies', None, True, False, True, False, False),
    ('VZ', 'Verizon Communications Inc.', -10.14, 'Your Verizon Stock Thesis Has One Loose End', None, True, False, True, False, True),
    ('HUM', 'Humana Inc.', 11.56, 'Humana Surges On 2027 CMS Ratings, Technical Breakout, Shares Fairly Priced', None, True, False, True, False, True),
    ('AAPL', 'Apple Inc.', -3.02, 'Apple Drops 3% on Reported iPhone 18 Pro Component Order Cuts; Skyworks Slips, Qualcomm Treads Water', None, True, False, False, False, True),
    ('QCOM', 'QUALCOMM Incorporated', 2.5, 'Qualcomm Treads Water as Apple Supplier Stocks Slip', 'flat', True, False, False, False, True),
    ('QCOM', 'QUALCOMM Incorporated', -1.2, 'Qualcomm Treads Water as Apple Supplier Stocks Slip', None, True, False, False, False, True),
    ('QCOM', 'QUALCOMM Incorporated', -3.1, 'Qualcomm Shares Little Changed After Apple Order Report', 'flat', True, False, False, False, True),
    ('AAPL', 'Apple Inc.', 0.8, 'Apple vs. Epic Ruling Lets Developers Link to Outside Payments', None, True, False, False, False, True),
    ('NVDA', 'NVIDIA Corporation', 1.4, 'Better Buy: Nvidia vs. AMD', None, True, False, True, False, False),
    ('NVDA', 'NVIDIA Corporation', -2.0, 'Nvidia Gains Approval to Sell Chips in China', None, True, False, False, False, True),
    ('NVDA', 'NVIDIA Corporation', -2.0, 'Nvidia Gains 4% on China Approval', 'verb_up_on_down', True, False, False, False, True),
    ('INTC', 'Intel Corporation', -3.0, 'Intel Steps Up Foundry Push With New Customer', None, True, False, False, False, True),
    ('COIN', 'Coinbase Global, Inc.', 4.3, 'Chevron’s Venezuela Plan Will Pay Off, Says Analyst. Plus, Coinbase and 3 More Stocks.', None, True, True, False, False, False),
    ('CEG', 'Constellation Energy Corporation', 4.56, 'Big Tech Needs Power. Constellation Just Found a $1 Billion Buyer in Google.', None, True, False, False, False, False),
    ('VEEV', 'Veeva Systems Inc.', 3.96, 'Reasons to Hold Veeva Systems Stock in Your Portfolio for Now', None, True, False, True, False, True),
    ('ORCL', 'Oracle Corporation', 4.21, 'Oracle vs. Cisco: The Dividend Battle Wall Street Didn’t See Coming', None, True, False, True, False, True),
    ('CRWD', 'CrowdStrike Holdings, Inc.', 4.57, "CrowdStrike Recommends Stockholders Reject Tutanota's $260/Share Mini-Tender Offer", None, True, False, False, False, True),
    ('DE', 'Deere & Company', -4.85, "Deere (DE) Stock Sinks As Market Gains: Here's Why", None, True, False, False, True, True),
    ('VZ', 'Verizon Communications Inc.', -10.14, 'Why Verizon (VZ) Shares Are Trading Lower Today', None, True, False, False, True, True),
    ('EL', 'The Estée Lauder Companies Inc.', 3.95, 'Estée Lauder Companies (EL) Gets A Bobbi Brown Reset On A Discount To Fair Value', None, True, False, True, False, True),
    ('COIN', 'Coinbase Global, Inc.', 4.3, 'Coinbase Has Lost 56% in a Year: Citizens JMP Sees 63% Upside', None, False, False, False, False, True),
    ('HPE', 'Hewlett Packard Enterprise Company', 3.46, 'Hewlett Packard Enterprise (HPE) Wins AI Infrastructure Deployment In Financial Services', None, True, False, False, False, True),
    ('ORCL', 'Oracle Corporation', 4.21, "Oracle vs. Cisco: The Dividend Battle Wall Street Didn't See Coming", None, True, False, True, False, True),
    ('AAPL', 'Apple Inc.', 0.8, 'Apple vs. Epic: Supreme Court Declines Appeal', None, True, False, False, False, True),
    ('KO', 'The Coca-Cola Company', 1.1, 'Coca-Cola versus PepsiCo: The Cola War Heats Up', None, True, False, True, False, True),
]


@pytest.mark.parametrize("sym,name,printed,headline,verdict,slot,roundup,opinion,explainer,leads", CASES,
                         ids=[f"{c[0]}:{c[2]}:{c[3][:40]}" for c in CASES])
def test_headline_verdict(sym, name, printed, headline, verdict, slot, roundup, opinion, explainer, leads):
    forms = name_forms(sym, name)
    reason = G.check(headline, printed, forms).reason
    assert (reason is None) if verdict is None else (reason or "").startswith(KINDS[verdict]), reason
    assert mover_slot_ok(headline, printed, forms) == slot
    assert is_roundup(headline) == roundup
    assert G.is_opinion(headline) == opinion
    assert G.is_explainer(headline) == explainer
    assert G.leads_with(headline, forms) == leads
    if roundup or opinion or not leads:                                       # shows nowhere: some rule of headline_problem keeps it out
        at = datetime(2026, 10, 9, 17, 0, tzinfo=timezone.utc)
        story = {"headline": headline, "source": "Yahoo", "published_at": at, "related": [sym], "url": headline}
        assert headline_problem(story, sym, name, date(2026, 7, 1), datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc)) is not None
