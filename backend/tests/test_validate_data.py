"""validate_data checks that are pure enough to test without a database."""


def test_a_stored_name_is_judged_against_secs_company_name_for_its_cik():
    # 2026-10-27: AXON was stored as another company's listing name; punctuation, case, accents, legal suffixes, listing words, SEC's
    # state tags and SEC's surname-first order never count (production's first read-only run flagged each of these)
    from app.scripts.validate_data import name_mismatches, names_match
    for ours, sec in (("The Coca-Cola Company", "COCA COLA CO"), ("PepsiCo, Inc. Common Stock", "PEPSICO INC"), ("Amazon.com, Inc.", "AMAZON COM INC"),
                      ("American Tower Corporation", "AMERICAN TOWER CORP /MA/"), ("A. O. Smith Corporation", "SMITH A O CORP"),
                      ("Casey's General Stores, Inc.", "CASEYS GENERAL STORES INC"), ("D.R. Horton, Inc.", "HORTON D R INC /DE/"),
                      ("C.H. Robinson Worldwide, Inc.", "C. H. ROBINSON WORLDWIDE, INC."), ("The Estée Lauder Companies Inc.", "ESTEE LAUDER COMPANIES INC"),
                      ("O'Reilly Automotive, Inc.", "O REILLY AUTOMOTIVE INC"), ("CRH plc", "CRH PUBLIC LTD CO"), ("Corning Incorporated", "CORNING INC /NY"),
                      ("Vertex Pharmaceuticals Incorporated", "VERTEX PHARMACEUTICALS INC / MA"), ("Wells Fargo & Company", "WELLS FARGO & COMPANY/MN"),
                      ("Willis Towers Watson Public Limited Company", "WILLIS TOWERS WATSON PLC"), ("JPMorgan Chase & Co.", "JPMORGAN CHASE & CO"), ("SLB N.V.", "SLB LIMITED/NV")):
        assert names_match(ours, sec), (ours, sec)
    assert not names_match("Axovant Sciences Ltd. Common Shares", "AXON ENTERPRISE, INC.")
    assert not names_match("GE Aerospace", "GENERAL ELECTRIC CO")
    # GE is a documented exception (Sam, 2026-10-27), only under the stored name it names
    from app.scripts.validate_data import NAME_EXCEPTIONS
    assert name_mismatches({"GE": "GE Aerospace"}, {"GE": "GENERAL ELECTRIC CO"}) == [] and "General Electric Company" in NAME_EXCEPTIONS["GE"][1]
    assert name_mismatches({"GE": "GE Vernova"}, {"GE": "GENERAL ELECTRIC CO"}) == ['GE: stored "GE Vernova" vs SEC "GENERAL ELECTRIC CO"']
    titles = {"AXON": "Axon Enterprise, Inc.", "PEP": "PEPSICO INC", "BRK.B": "BERKSHIRE HATHAWAY INC"}
    stored = {"AXON": "Axovant Sciences Ltd. Common Shares", "PEP": "PepsiCo, Inc. Common Stock", "BRK-B": "Berkshire Hathaway Inc.", "ZZZ": "Not Listed"}
    assert name_mismatches(stored, titles) == ['AXON: stored "Axovant Sciences Ltd. Common Shares" vs SEC "Axon Enterprise, Inc."']
