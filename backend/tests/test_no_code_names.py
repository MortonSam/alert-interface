"""Customer-facing text never names a code file, function or path. Every visitor GET endpoint (admin, live quote and news fetches,
and AI-written explanations excepted) is called on the test database for a few tickers, and every prose string in its response
(three words or more) is checked. frontend lib/__tests__/noCodeNames.test.ts holds the same rule for the pages' own copy."""
import re

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.xdist_group(name="no_code_names")

CODE_PATTERNS = [
    ("file", re.compile(r"\b[\w-]+\.(?:tsx?|jsx?|py|json|md|css|sh|sql|ya?ml)\b")),
    ("path", re.compile(r"\b(?:src|app|lib|components|services|routers|scripts|backend|frontend|tests|ops)/[\w.-]")),
    ("function", re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\(\)")),
    ("identifier", re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b")),
    ("identifier", re.compile(r"\b[a-z]+[A-Z][A-Za-z0-9]+\b")),
]
ALLOWED = {"iPhone", "iPad", "eBay"}
SKIP = ("/admin", "/quote", "/quotes", "/news", "/chart/", "/explain/", "/options-read/", "/batch-enrich", "/system/status", "/health")
PROSE_KEYS = {"source", "rule", "how", "note", "reason", "text", "data", "idea", "message", "summary", "label", "detail", "caption"}
SYMBOLS = ("AAPL", "PANW", "JPM")


def code_names(text: str) -> list[str]:
    """The code names a piece of prose carries, as 'kind: match'."""
    hits = []
    for kind, pat in CODE_PATTERNS:
        hits += [f"{kind}: {m.group(0)}" for m in pat.finditer(text) if m.group(0) not in ALLOWED]
    return hits


def test_the_rule_catches_code_and_passes_prose():
    assert code_names("Cutoffs come from lib/thresholds.ts.") and code_names("see compute_expected_move()") and code_names("the iv_rank field")
    assert not code_names("The options on PANW are expensive right now, about 14.1% against a usual 9.4%.")
    assert not code_names("Put/call ratio above 1.2 reads put-heavy; U.S. markets close at 4:00 p.m. ET.")


def prose(value, where: str):
    """Strings a visitor reads: three words or more anywhere, and any string under a key that holds copy (a source can be one word)."""
    if isinstance(value, str):
        key = where.rsplit(".", 1)[-1].split("[")[0]
        if (value.count(" ") >= 2 or key in PROSE_KEYS) and not value.startswith(("http://", "https://")):
            yield where, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from prose(v, f"{where}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from prose(v, f"{where}[{i}]")


def visitor_paths() -> list[str]:
    out = []
    for path, ops in app.openapi()["paths"].items():
        if "get" not in ops or not path.startswith("/api/v1") or any(s in path for s in SKIP):
            continue
        params = re.findall(r"\{(\w+)\}", path)
        if not params:
            out.append(path)
        elif params == ["symbol"]:
            out += [path.replace("{symbol}", s) for s in SYMBOLS]
    return out


@pytest.mark.asyncio
async def test_no_visitor_response_names_code():
    paths = visitor_paths()
    assert any("/expected-move/" in p for p in paths) and any(p.endswith("/briefing") for p in paths) and any("/ivy-rule" in p for p in paths)
    found, served = [], 0
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        for path in paths:
            resp = await c.get(path)
            if resp.status_code != 200 or "json" not in resp.headers.get("content-type", ""):
                continue
            served += 1
            for where, text in prose(resp.json(), path):
                found += [f"{where}: {h} in {text[:120]!r}" for h in code_names(text)]
    assert served >= 20, served
    assert not found, "\n".join(found[:40])
