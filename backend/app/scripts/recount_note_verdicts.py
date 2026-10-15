"""Stored research notes whose verification disagrees with itself (validate note_verdicts) are corrected in code, without
regenerating or re-verifying them: the summary is recounted from the claims' verdicts (verification_verdicts.summary_of), a claim
with no known verdict takes the fallback, and a claim whose reason corrects itself takes the outcome the verifier gives after a
second such answer: unsupported, its reason replaced by UNSETTLED_REASON (the reason it had is kept as prior_reason). Claim text
is never changed. Each note is updated only if its verification is still the one read.

Usage
-----
    python -m app.scripts.recount_note_verdicts            # dry run, read only: each note before and after
    python -m app.scripts.recount_note_verdicts --write    # writes exactly the notes listed
"""
from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.verification_verdicts import FALLBACK, UNSETTLED_REASON, VERDICTS, problems, self_corrected, summary_of

ROWS = text("""SELECT r.id, t.symbol, r.verified_at, r.verification FROM research_notes r JOIN tickers t ON t.id = r.ticker_id
    WHERE r.verification IS NOT NULL ORDER BY t.symbol""")


def recount(ver: dict) -> tuple[dict, list[str]]:
    """Pure: (the verification with one settled verdict per claim and the summary counted from them, what changed per claim)."""
    claims, changes = [], []
    for i, c in enumerate(x for x in ver.get("claims") or [] if isinstance(x, dict)):
        verdict = str(c.get("verdict") or c.get("status") or "").strip().lower()
        reason = c.get("reason") if c.get("reason") is not None else c.get("evidence")
        new = dict(c)
        if verdict not in VERDICTS:
            changes.append(f"claim {i + 1}: verdict {verdict!r} -> {FALLBACK}")
            verdict = FALLBACK
        if self_corrected(reason, verdict):
            changes.append(f"claim {i + 1}: {verdict} -> unsupported, the reason corrected itself: {str(reason)[:160]!r}")
            new["prior_reason"] = reason
            verdict, reason = "unsupported", UNSETTLED_REASON
        new["verdict"], new["reason"] = verdict, reason
        if "status" in c:
            new["status"] = verdict
        if "evidence" in c:
            new["evidence"] = reason
        claims.append(new)
    out = {**ver, "claims": claims, "summary": summary_of(claims)}
    stored = ver.get("summary") or {}
    if any(stored.get(v) != out["summary"][v] for v in VERDICTS):
        changes.append(f"summary {json.dumps({v: stored.get(v) for v in VERDICTS})} -> {json.dumps(out['summary'])}")
    return out, changes


async def run(write: bool) -> int:
    async with ScriptSessionLocal() as s:
        if not write:
            await s.execute(text("SET TRANSACTION READ ONLY"))
        rows = (await s.execute(ROWS)).all()
        fix = []
        for r in rows:
            ver = r.verification if isinstance(r.verification, dict) else None
            ps = problems(ver)
            if not ps or ver is None or not isinstance(ver.get("claims"), list):
                continue
            new, changes = recount(ver)
            assert problems(new) == [], (r.symbol, problems(new))
            fix.append((r, ver, new))
            print(f"\n{r.symbol} (verified {r.verified_at:%Y-%m-%d}): {'; '.join(ps)}")
            print(f"  before: {json.dumps(ver.get('summary'))}  after: {json.dumps(new['summary'])}")
            for c in changes:
                print(f"    {c}")
        print(f"\n{len(rows)} note(s) with a verification, {len(fix)} to correct")
        if write and fix:
            n = 0
            for r, old, new in fix:
                n += (await s.execute(text("UPDATE research_notes SET verification = CAST(:new AS jsonb) WHERE id = :id AND verification = CAST(:old AS jsonb)"),
                                      {"id": r.id, "new": json.dumps(new), "old": json.dumps(old)})).rowcount
            await s.commit()
            print(f"written: {n} note(s) corrected")
        else:
            await s.rollback()
            print("dry run: nothing written (add --write)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(asyncio.wait_for(run("--write" in sys.argv), 120)))
