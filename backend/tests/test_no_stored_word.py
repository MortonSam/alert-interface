"""The word "stored" never appears in visible copy (Sam, 2026-10-19): a visitor reads "on file", or nothing. Two checks: every string
literal in the routers, services and schemas (docstrings, model prompts, logs, alerts and validate's own messages excepted, listed
below), and every prose string a visitor GET returns on the test database (test_no_code_names' endpoints and rule for prose).
frontend lib/__tests__/noStoredWord.test.ts holds the same rule for the pages' own copy."""
import ast
import pathlib
import re

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.test_no_code_names import prose, visitor_paths

pytestmark = pytest.mark.xdist_group(name="no_code_names")

STORED = re.compile(r"\bstored\b", re.I)
APP = pathlib.Path(__file__).resolve().parents[1] / "app"
# modules whose strings a visitor never reads: validate's chain verdicts, the hidden-rows note, the quote log line, the ntfy alerts,
# the security-record table's internal names, and the research-note prompt's evidence headings
INTERNAL_FILES = {"services/chain_shadow.py", "services/price_history_exclusion.py", "services/finnhub_client.py", "services/notify.py",
                  "services/security_records.py", "services/note_comparisons.py", "services/research_note_service.py"}
# Ask Ivy's model prompts, its verifier's prompt, its forbidden-phrase pattern and the problems its checker logs
INTERNAL_PHRASES = ("ONLY the stored facts", "STORED FACTS", "against the stored facts ONLY", "(no facts stored)", "the stored facts|", "\"the facts here\", \"stored\"",
                    "has no stored comparison", "contradicts the stored comparison")


def literal_hits() -> list[str]:
    out = []
    for p in sorted(APP.rglob("*.py")):
        rel = p.relative_to(APP).as_posix()
        if not rel.startswith(("routers/", "services/", "schemas/")) or rel in INTERNAL_FILES:
            continue
        tree = ast.parse(p.read_text())
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(tree):
            if (isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and STORED.search(n.value)
                    and not any(x in n.value for x in INTERNAL_PHRASES)):
                out.append(f"{rel}:{n.lineno}: {n.value[:120]!r}")
    return out


def test_the_rule_catches_the_word():
    assert STORED.search("No EPS figure is stored for this report.") and STORED.search("Stored daily closes")
    assert not STORED.search("No EPS figure is on file for this report.") and not STORED.search("restored")


def test_no_backend_sentence_says_stored():
    hits = literal_hits()
    assert not hits, "\n".join(hits)


@pytest.mark.asyncio
async def test_no_visitor_response_says_stored():
    found, served = [], 0
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        for path in visitor_paths():
            resp = await c.get(path)
            if resp.status_code != 200 or "json" not in resp.headers.get("content-type", ""):
                continue
            served += 1
            found += [f"{where}: {text[:120]!r}" for where, text in prose(resp.json(), path) if STORED.search(text)]
    assert served >= 20, served
    assert not found, "\n".join(found[:40])
