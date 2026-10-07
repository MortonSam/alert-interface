"""Release EPS against XBRL: for each stored release figure not yet checked, look for the same quarter in the company's XBRL
facts (a 10-Q or 10-K filed after the report); when found, store the XBRL figure and flag a difference over $0.01.

    python -m app.scripts.check_release_eps            # the nightly step; prints and records every flag
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.edgar_client import EdgarClient
from app.services.redact import redact
from app.services.step_outcomes import record_step_fields
from app.services.valuation import eps_quarters, release_difference

STEP_LABEL = "Release EPS vs XBRL"
END_TOLERANCE_DAYS = 7


def matching_quarter(quarters: list[dict], period_end: date | None, report_date: date) -> dict | None:
    """Pure: the XBRL quarter the release described: the one ending within END_TOLERANCE_DAYS of the stated period end, else
    the newest quarter ending before the report date and filed after it."""
    if period_end:
        near = [q for q in quarters if abs((q["end"] - period_end).days) <= END_TOLERANCE_DAYS]
        if near:
            return near[-1]
    later = [q for q in quarters if q["end"] < report_date and q["filed"] >= report_date]
    return later[-1] if later else None


async def run() -> int:
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("SELECT id, symbol, report_date, period_end, diluted_eps_gaap FROM release_eps WHERE xbrl_eps IS NULL ORDER BY symbol"))).all()
    print(f"{STEP_LABEL}: {len(rows)} release figure(s) awaiting XBRL", flush=True)
    edgar = EdgarClient()
    checked = flagged = pending = 0
    flags = []
    try:
        for rid, sym, report_date, period_end, rel in rows:
            try:
                cik = await edgar.get_cik(sym)
                quarters = eps_quarters(await edgar.get_company_facts(cik)) if cik else []
                q = matching_quarter(quarters, period_end, report_date)
                if q is None or q["filed"] < report_date:
                    pending += 1; continue
                diff, flag = release_difference(float(rel), q["eps"])
                checked += 1
                print(f"  {sym} {report_date}: release {float(rel):+.2f} vs XBRL {q['eps']:+.2f} ({q['form']} filed {q['filed']}): difference {diff:+.4f}" + ("  FLAG" if flag else ""))
                if flag:
                    flagged += 1; flags.append(f"{sym} {report_date}: release {float(rel):+.2f} vs XBRL {q['eps']:+.2f}")
                async with ScriptSessionLocal() as s:
                    await s.execute(text("UPDATE release_eps SET xbrl_eps = :x, xbrl_form = :f, xbrl_checked_at = now(), difference = :d, flagged = :fl WHERE id = :id"),
                                    {"x": q["eps"], "f": q["form"][:10], "d": diff, "fl": flag, "id": rid})
                    await s.commit()
            except Exception as exc:
                print(f"  {sym} {report_date}: failed: {redact(exc)[:120]}")
    finally:
        await edgar.close()
    print(f"  checked {checked}, flagged {flagged}, still pending {pending}")
    await record_step_fields(STEP_LABEL, {"awaiting": len(rows), "checked": checked, "flagged": flagged, "pending": pending, "flags": flags, "error": None})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
