"""The Item 1A reader against the forms the 42 unread 10-Ks of Nov 10, 2026 use (services/risk_factors, version 4)."""
from app.services import risk_factors as R

BODY = "<p>" + "The company could lose money in many ways that are described at length here. " * 12 + "</p>"
END = '<p><b>Item 1B. Unresolved Staff Comments</b></p><p>None.</p>'


def _doc(heading: str, risks: list[str]) -> str:
    return '<html><head><meta charset="utf-8"></head><body>' + heading + "".join(r + BODY for r in risks) + END + "</body></html>"


def _headings(html: str) -> list[str]:
    got = R.read_html(html)
    assert got["ok"], got
    return [r["heading"] for r in got["risks"]]


THREE = ["We face intense competition in every market we serve today.", "Changes in interest rates could reduce our income from loans.",
         "A cybersecurity incident could disrupt our operations and harm us."]


def test_item_headings_in_the_forms_filers_use():
    for heading in ('<p><b>ITEM 1A | Risk Factors</b></p>',                           # AIG, HIG: and again as each page's running head
                    '<p>Part I - Item 1A. Risk Factors</p>', '<p>ITEM 1A. &#8212; RISK FACTORS</p>', '<p>Item 1.A. Risk Factors</p>',
                    '<p>Item 1(a). Risk Factors.</p>', '<p>Item 1A.</p><p>Risk Factors</p>',
                    '<h2>Item 1A. Ris<span>k Factors</span></h2>',                       # ZBH: an h2, the words split across spans
                    '<div><span><b>ITEM 1A.&#160;RISK FACTORS</b></span><table><tr><td></td></tr></table></div>',    # ABBV: a rule set as a table
                    '<p>ITEM 1A. RISK FACTORS (dollars in millions, except per share amounts)</p>'):                  # NEM
        assert _headings(_doc(heading, [f"<p><b>{r}</b></p>" for r in THREE])) == THREE, heading


def test_a_lone_risk_factors_heading_when_the_body_has_no_item_headings():
    html = "<html><body><p><b>Risk Factors</b></p>" + "".join(f"<p><b>{r}</b></p>" + BODY for r in THREE) + \
           "<p><b>Properties</b></p><p>" + "Our offices are leased. " * 200 + "</p></body></html>"
    assert _headings(html) == THREE


def test_heading_styles_and_markers():
    styled = ['<p><span style="text-decoration:underline">' + THREE[0] + "</span></p>",                       # TXN
              '<p><span style="font-weight:400">&#8226;</span><span style="font-weight:700">' + THREE[1] + "</span></p>",   # NOC
              "<p><b>&#9632;" + THREE[2] + "</b></p>"]                                                                  # AOS
    assert _headings(_doc("<p><b>Item 1A. Risk Factors</b></p>", styled)) == THREE
    assert _headings(_doc("<p><b>Item 1A. Risk Factors</b></p>", [f"<p><b>{c}.{r}</b></p>" for c, r in zip("abc", THREE)])) == THREE   # CCL
    caps = "WE ARE SUBJECT TO A VARIETY OF RISKS DUE TO OUR OPERATIONS OUTSIDE OF THE U.S."                     # ISRG
    assert _headings(_doc("<p><b>Item 1A. Risk Factors</b></p>", [f"<p><b>{caps}</b></p>"] + [f"<p><b>{r}</b></p>" for r in THREE[1:]]))[0] == caps


def test_labels_running_heads_and_a_summary_are_not_risks():
    labels = ["<p><b>Copyright and other intellectual property matters:</b></p>", "<p><b>Table of Contents Index to Financial Statements</b></p>"]
    summary = "".join(f"<p><b>{r}</b></p><p>&#8226;</p>" for r in THREE)                                    # WTW: the summary lists them first
    got = _headings(_doc("<p><b>Item 1A. Risk Factors</b></p>" + summary, [f"<p><b>{r}</b></p>" for r in THREE] + labels))
    assert got == THREE
    lead = "<p><b>Downturn in Client Spending Could Impact the Company's Business:</b> " + "Clients may spend less. " * 30 + "</p>"   # IBM
    assert _headings(_doc("<p><b>Item 1A. Risk Factors</b></p>", [lead] + [f"<p><b>{r}</b></p>" for r in THREE]))[0] == \
        "Downturn in Client Spending Could Impact the Company's Business:"
