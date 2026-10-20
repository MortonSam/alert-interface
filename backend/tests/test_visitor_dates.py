"""A sentence a visitor reads carries the site's one date format, "Oct 23, 2026" (services/dates.fmt_day, frontend DESIGN.md), never an
ISO date. The scan flags any f-string in a service or router that interpolates .isoformat() or a [:10] slice; internal notes (validate
rows, admin lines, cache and API keys, logs, the headline guard's reasons) are listed by file and kept ISO."""
import re
from pathlib import Path

from app.services.dates import fmt_day, fmt_days_in
from app.services.implied_move import expiry_caveat
from app.scripts.snapshot_iv import null_iv_reason

APP = Path(__file__).resolve().parents[1] / "app"
INTERNAL = {"services/pick_void.py", "services/corporate_actions.py", "services/security_records.py", "services/fomc_calendar.py",
            "services/news.py", "services/ir_feeds.py", "services/intrinio_client.py", "routers/admin.py",
            "services/report_date_reader.py",       # the confirmation reader's notes: the page reads them through confirmedKind, never raw
            "services/research_note_service.py"}    # the research-note model prompt
ISO_IN_FSTRING = re.compile(r'f"[^"\n]*\{[^}\n]*(?:\.isoformat\(\)|\[:10\])[^}\n]*\}[^"\n]*"')
NOT_A_SENTENCE = re.compile(r"logger\.|print\(|log\.|key|url|params|cache|SELECT|WHERE|_input\(|\"date\":|f\"/|f\"\{[^}]*\}:\{")


def test_no_visitor_sentence_prints_an_iso_date():
    hits = []
    for p in sorted((APP / "services").glob("*.py")) + sorted((APP / "routers").glob("*.py")):
        rel = str(p.relative_to(APP))
        if rel in INTERNAL:
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if ISO_IN_FSTRING.search(line) and not NOT_A_SENTENCE.search(line):
                hits.append(f"{rel}:{i}: {line.strip()[:120]}")
    assert hits == []


def test_the_sentences_fixed_on_2026_10_16_read_the_one_format():
    assert fmt_day("2026-10-23") == "Oct 23, 2026" and fmt_day(None) is None
    assert expiry_caveat("2026-11-20", "2026-10-20").startswith("Nearest available expiration (Nov 20, 2026) is 31 days after the Oct 20, 2026 earnings date.")
    assert null_iv_reason(None, 900.0, "2026-10-16") == "no implied volatility on the ATM strike for expiration Oct 16, 2026"
    assert fmt_days_in("no implied volatility on the ATM strike for expiration 2026-10-16") == "no implied volatility on the ATM strike for expiration Oct 16, 2026"


def test_ivys_written_text_is_served_with_the_one_format():
    """Ivy's Read and the metric explanations are written by a model from facts that carry ISO days ("The 2026-12-18 expiration falls
    64 calendar days after ..."); every served content runs through fmt_days_in, cached or new."""
    src = (APP / "routers" / "tickers.py").read_text()
    served = re.findall(r"content=([^,\n]+),", src)
    written = [c for c in served if "content" in c and c != '""']
    assert len(written) == 4 and all(c.startswith("fmt_days_in(") for c in written), written
    assert fmt_days_in("The 2026-12-18 expiration falls 64 calendar days after the 2026-10-15 earnings date") == \
        "The Dec 18, 2026 expiration falls 64 calendar days after the Oct 15, 2026 earnings date"


def test_a_calendar_note_written_before_the_format_reads_in_it():
    from app.services.briefing import reader_note
    assert reader_note("the last report was 2026-07-22, so a quarterly report would usually be due around 2026-10-21") == \
        "the last report was Jul 22, 2026, so a quarterly report would usually be due around Oct 21, 2026"
