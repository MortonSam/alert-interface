"""LICENSED_ESTIMATES (services/licensed_estimates): off (the default), no estimate, beat, miss, surprise, beat rate or provider
actual leaves the API, and each place that showed one carries the reported EPS from SEC filings against the same quarter a year
earlier instead; on, today's behaviour. The crawl reads the copied dev data (NVDA: reactions with estimates and actuals,
SEC quarters, a research note)."""
import json
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.services import licensed_estimates as LE
from app.services.eps_year_ago import year_ago_pairs

pytestmark = pytest.mark.xdist_group(name="licensed_estimates")

SYM = "NVDA"
# every endpoint a page reads that showed an estimate, a beat or miss, a surprise or a beat rate
ENDPOINTS = [f"/api/v1/reactions?symbol={SYM}", f"/api/v1/reactions/summary?symbol={SYM}", f"/api/v1/reactions/conditional?symbol={SYM}",
             f"/api/v1/tickers/chart/{SYM}?period=5y", f"/api/v1/tickers/{SYM}/briefing", f"/api/v1/tickers/{SYM}/questions",
             "/api/v1/discover/just-reported?days=30&limit=50", "/api/v1/discover/reporting-soon?days=30&limit=50",
             "/api/v1/discover/suggestions", f"/api/v1/discover/insight/{SYM}", f"/api/v1/research-notes?symbol={SYM}",
             "/api/v1/research-notes/latest-verified", "/api/v1/theses/alert-picks", "/api/v1/theses"]
OK_STRING_KEYS = {"confirmation", "earnings_confirmation", "event_confirmation", "as_of_kind", "source", "earnings_source",
                  "confirmation_note", "earnings_note", "note", "rule", "status", "symbol", "name", "company_name"}


def _leaks(node, path="") -> list[str]:
    """Every non-null estimate field, and every string naming a beat, miss, estimate or surprise, in a JSON body."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in LE.ESTIMATE_FIELDS and v not in (None, 0, [], {}):
                out.append(f"{path}.{k} = {v!r}")
            elif k == "outcome" and v in ("beat", "miss", "meet"):
                out.append(f"{path}.outcome = {v}")
            else:
                out += _leaks(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _leaks(v, f"{path}[{i}]")
    elif isinstance(node, str) and LE.mentions_estimates(node) and path.rsplit(".", 1)[-1] not in OK_STRING_KEYS:
        out.append(f"{path} = {node[:120]!r}")
    return out


async def _crawl(monkeypatch) -> dict[str, object]:
    """Every endpoint read as the admin, who sees the most (the ledger and void picks included)."""
    from app import auth
    from app.main import app
    monkeypatch.setattr(auth.settings, "admin_token", "zz-licensed-test")
    bodies = {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers={"X-Admin-Token": "zz-licensed-test"}) as c:
        for url in ENDPOINTS:
            r = await c.get(url)
            bodies[url] = r.json() if r.status_code == 200 else None
    return bodies


@pytest.mark.asyncio
async def test_nothing_estimate_based_leaves_the_api_with_the_setting_off(monkeypatch):
    monkeypatch.setattr(settings, "licensed_estimates", False)
    bodies = await _crawl(monkeypatch)
    leaks = {url: _leaks(b) for url, b in bodies.items() if b is not None}
    assert not any(leaks.values()), json.dumps({u: l[:8] for u, l in leaks.items() if l}, indent=1)
    rows = bodies[f"/api/v1/reactions?symbol={SYM}"]
    earnings = [r for r in rows if r["event_type"] == "earnings"]
    assert earnings and all(r["licensed_estimates"] is False and r["eps_estimate"] is None and r["outcome"] == "unknown" for r in earnings)
    lines = [r["eps_line"] for r in earnings if r["eps_line"]]
    assert lines and all(x.startswith("EPS $") for x in lines)
    assert any(" a year ago" in x for x in lines)
    summary = bodies[f"/api/v1/reactions/summary?symbol={SYM}"]
    assert summary["licensed_estimates"] is False and summary["beat_count"] is None and summary["beat_rate_pct"] is None
    assert bodies[f"/api/v1/tickers/chart/{SYM}?period=5y"]["licensed_estimates"] is False
    assert "beat_fell" not in [q["key"] for q in bodies[f"/api/v1/tickers/{SYM}/questions"]["questions"]]
    assert all(bodies[u] is not None for u in ENDPOINTS if "latest-verified" not in u), [u for u in ENDPOINTS if bodies[u] is None and "latest-verified" not in u]
    jr = bodies["/api/v1/discover/just-reported?days=30&limit=50"]["items"]
    assert all(i["licensed_estimates"] is False and i["outcome"] == "unknown" for i in jr)


@pytest.mark.asyncio
async def test_with_the_setting_on_the_estimates_are_served_as_before(monkeypatch):
    monkeypatch.setattr(settings, "licensed_estimates", True)
    bodies = await _crawl(monkeypatch)
    rows = [r for r in bodies[f"/api/v1/reactions?symbol={SYM}"] if r["event_type"] == "earnings"]
    assert any(r["eps_estimate"] is not None for r in rows) and all(r["licensed_estimates"] is True for r in rows)
    assert any(r["outcome"] in ("beat", "miss", "meet") for r in rows)
    assert bodies[f"/api/v1/reactions/summary?symbol={SYM}"]["beat_count"] is not None


@pytest.mark.asyncio
async def test_ask_ivy_facts_name_no_estimate_with_the_setting_off(monkeypatch):
    from app.database import ScriptSessionLocal
    from app.services.ask_ivy import fact_pack
    monkeypatch.setattr(settings, "licensed_estimates", False)
    async with ScriptSessionLocal() as db:
        pack = await fact_pack(db, SYM, date.today())
    ids = {f["id"] for f in pack["facts"]}
    assert not ids & {"eps_estimate", "eps_actual", "outcome", "last_report_outcome", "beats", "beats_followed_by_a_fall"}
    assert not [f for f in pack["facts"] if LE.mentions_estimates(str(f.get("value"))) or LE.mentions_estimates(f.get("phrase"))]
    assert not [c for c in pack["context"] if LE.mentions_estimates(c)]


def test_the_year_ago_line_and_the_plain_absence():
    pairs = year_ago_pairs([(date(2025, 7, 27), 1.05), (date(2026, 7, 26), 2.22), (date(2026, 4, 26), 2.39)])
    ya = LE.YearAgo(pairs)
    assert ya.for_report(date(2026, 8, 26))["eps_line"] == "EPS $2.22, up 111.4% from $1.05 a year ago"
    assert ya.for_report(date(2026, 5, 28))["eps_line"] == "EPS $2.39. No EPS figure from the same quarter a year earlier is on file."
    assert ya.for_report(date(2027, 3, 1))["eps_line"] is None
    from app.services.briefing import year_ago_clause
    assert year_ago_clause(ya.for_report(date(2026, 5, 28))) == "EPS $2.39, with no figure from the same quarter a year earlier on file"


def test_stored_text_and_notes_lose_their_estimate_sentences():
    assert LE.filter_text("Momentum is negative. It beat estimates in 18 of 20 quarters. Options are rich.") == "Momentum is negative. Options are rich."
    note = {"highlights": [{"lead": "Beat history", "detail": "Beat in 18 of 20."}, {"lead": "Margins", "detail": "Up from a year earlier."}],
            "watch": [], "risks": [], "bottom_line": "A consensus beat is likely. Watch margins.", "stats": {"eps_estimate": 1.0, "market_cap": 5}}
    ver = {"claims": [{"claim": "It beat consensus.", "verdict": "supported"}, {"claim": "Margins rose.", "verdict": "supported"}]}
    s, v = LE.filter_note(note, ver)
    assert [p["lead"] for p in s["highlights"]] == ["Margins"] and s["bottom_line"] == "Watch margins."
    assert s["stats"] == {"eps_estimate": None, "market_cap": 5} and [c["claim"] for c in v["claims"]] == ["Margins rose."]
    assert LE.filter_receipt({"beat_rate": 90.0, "momentum_20d": -20, "reasoning": "Beat rate is 90%. Momentum is weak."}) == \
        {"momentum_20d": -20, "reasoning": "Momentum is weak."}
    assert not LE.mentions_estimates("Reports Oct 20 (estimated)") and LE.mentions_estimates("EPS beat the estimate")


def test_the_setting_is_off_by_default():
    from app.config import Settings
    assert Settings.model_fields["licensed_estimates"].default is False
