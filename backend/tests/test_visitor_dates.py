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
            "services/news.py", "services/ir_feeds.py", "services/intrinio_client.py", "routers/admin.py"}
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
