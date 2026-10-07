"""Release EPS against XBRL: for each stored release figure not yet checked, look for the same quarter among the quarters the
company's XBRL facts report directly (a 10-Q or 10-K filed after the report); when found, store the XBRL figure and flag a
difference over $0.01. A quarter XBRL holds only by derivation (the 10-K's annual figure less the three 10-Qs) is never
compared: the annual weighted-average share count is not the quarter's, so after a share issuance the subtraction is not the
quarter's EPS (PANW, 112 million shares issued for CyberArk in February 2026: derived -0.46 against the stated -0.35). Such a
row is recorded as not comparable (xbrl_note) with no XBRL figure and no flag.

Every flagged row is re-judged on every run (a flagged PANW clears the night this rule ships), so the nightly needs no hand run.

    python -m app.scripts.check_release_eps                    # the nightly step: unchecked rows and flagged rows; prints and records every flag
    python -m app.scripts.check_release_eps --recheck-flagged  # the flagged rows alone
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.edgar_client import EdgarClient
from app.services.redact import redact
from app.services.write_failures import WriteFailures
from app.services.write_failures import WriteFailures
from app.services.step_outcomes import record_step_fields
from app.services.valuation import eps_quarters, release_difference

STEP_LABEL = "Release EPS vs XBRL"
WRITES = WriteFailures(STEP_LABEL)
WRITES = WriteFailures(STEP_LABEL)
END_TOLERANCE_DAYS = 7
NOT_COMPARABLE = ("XBRL holds this quarter only as a derived figure ({form} annual less three quarters, filed {filed}); "
                  "a release figure is compared only with a quarter XBRL reports directly")


def _match(candidates: list[dict], period_end: date | None, report_date: date) -> dict | None:
    if period_end:
        near = [q for q in candidates if abs((q["end"] - period_end).days) <= END_TOLERANCE_DAYS]
        if near:
            return near[-1]
    later = [q for q in candidates if q["end"] < report_date and q["filed"] >= report_date]
    return later[-1] if later else None


def matching_quarter(quarters: list[dict], period_end: date | None, report_date: date) -> dict | None:
    """Pure: the XBRL quarter the release described, among the quarters XBRL reports directly: the one ending within
    END_TOLERANCE_DAYS of the stated period end, else the newest quarter ending before the report date and filed after it.
    A derived quarter (valuation.eps_quarters: the annual figure less three quarters) is never a match."""
    return _match([q for q in quarters if not q.get("derived")], period_end, report_date)


def derived_only_match(quarters: list[dict], period_end: date | None, report_date: date) -> dict | None:
    """Pure: the derived quarter the release described, for the not-comparable verdict when no direct quarter matches."""
    return _match([q for q in quarters if q.get("derived")], period_end, report_date)


async def run(recheck_flagged: bool = False) -> int:
    where = "flagged" if recheck_flagged else "(xbrl_checked_at IS NULL OR flagged)"
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text(f"SELECT id, symbol, report_date, period_end, diluted_eps_gaap FROM release_eps WHERE {where} ORDER BY symbol"))).all()
    print(f"{STEP_LABEL}: {len(rows)} release figure(s) {'flagged, re-judged' if recheck_flagged else 'awaiting XBRL or flagged'}", flush=True)
    edgar = EdgarClient()
    checked = flagged = pending = not_comparable = 0
    flags = []
    try:
        for rid, sym, report_date, period_end, rel in rows:
            try:
                cik = await edgar.get_cik(sym)
                quarters = eps_quarters(await edgar.get_company_facts(cik)) if cik else []
                q = matching_quarter(quarters, period_end, report_date)
                if q is None or q["filed"] < report_date:
                    d = derived_only_match(quarters, period_end, report_date)
                    if d is not None and d["filed"] >= report_date:
                        not_comparable += 1
                        note = NOT_COMPARABLE.format(form=d["form"], filed=d["filed"])
                        print(f"  {sym} {report_date}: release {float(rel):+.2f}: not comparable; {note}")
                        async with ScriptSessionLocal() as s:
                            await s.execute(text("UPDATE release_eps SET xbrl_eps = NULL, xbrl_form = :f, xbrl_checked_at = now(), difference = NULL, flagged = false, xbrl_note = :n WHERE id = :id"),
                                            {"f": d["form"][:10], "n": note, "id": rid})
                            await s.commit()
                        continue
                    pending += 1; continue
                diff, flag = release_difference(float(rel), q["eps"])
                checked += 1
                print(f"  {sym} {report_date}: release {float(rel):+.2f} vs XBRL {q['eps']:+.2f} ({q['form']} filed {q['filed']}): difference {diff:+.4f}" + ("  FLAG" if flag else ""))
                if flag:
                    flagged += 1; flags.append(f"{sym} {report_date}: release {float(rel):+.2f} vs XBRL {q['eps']:+.2f}")
                async with ScriptSessionLocal() as s:
                    await s.execute(text("UPDATE release_eps SET xbrl_eps = :x, xbrl_form = :f, xbrl_checked_at = now(), difference = :d, flagged = :fl, xbrl_note = NULL WHERE id = :id"),
                                    {"x": q["eps"], "f": q["form"][:10], "d": diff, "fl": flag, "id": rid})
                    await s.commit()
            except Exception as exc:
                WRITES.note(f"{sym} {report_date}", exc)
                print(f"  {sym} {report_date}: failed: {redact(exc)[:120]}")
    finally:
        await edgar.close()
    print(f"  checked {checked}, flagged {flagged}, not comparable {not_comparable}, still pending {pending}")
    await record_step_fields(STEP_LABEL, {"awaiting": len(rows), "checked": checked, "flagged": flagged, "not_comparable": not_comparable, "pending": pending, "flags": flags, "error": None})
    return await WRITES.finish(0)


if __name__ == "__main__":
    sys.exit(asyncio.run(run(recheck_flagged="--recheck-flagged" in sys.argv[1:])))
