"""Market value from the cover page against the vendor's (Sam, 2026-11-10): for every active index member, its latest 10-Q or 10-K
cover's shares outstanding (every class summed, services/market_value) times its latest licensed close, set beside tickers.market_cap.
Reads only; writes a JSON report.

    python -m app.scripts.market_value_report /tmp/market_value.json
"""
from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import market_value as MV
from app.services.edgar_client import EdgarClient

DIFFERS_PCT = 3.0


async def run(argv: list[str]) -> int:
    out_path = argv[0] if argv else "/tmp/market_value.json"
    async with ScriptSessionLocal() as db:
        rows = (await db.execute(text("""SELECT t.symbol, t.market_cap, t.market_cap_updated_at, b.date AS close_date, b.close
            FROM tickers t LEFT JOIN LATERAL (SELECT date, close FROM price_bars_shadow WHERE symbol = t.symbol ORDER BY date DESC LIMIT 1) b ON true
            WHERE t.is_active AND t.index_member ORDER BY t.symbol"""))).all()
        splits = {(r[0]): r[1] for r in (await db.execute(text("""SELECT t.symbol, max(e.event_date) FROM events e JOIN tickers t ON t.id = e.ticker_id
            WHERE e.event_type = 'split' GROUP BY t.symbol"""))).all()}
    edgar = EdgarClient()
    out = []
    try:
        for r in rows:
            item = {"symbol": r.symbol, "vendor": float(r.market_cap) if r.market_cap else None, "close": float(r.close) if r.close else None,
                    "close_date": str(r.close_date) if r.close_date else None}
            try:
                cik = await edgar.get_cik(r.symbol.replace(".", "-"))
                if cik is None:
                    item["why"] = "no CIK for the symbol"
                else:
                    f = MV.latest_cover_filing(await edgar.get_submissions(cik))
                    if f is None:
                        item["why"] = "no 10-Q or 10-K"
                    else:
                        html = await edgar.fetch_filing_html(cik, f["accession"], f["document"])
                        cover = MV.cover_shares(html)
                        item.update({"cik": cik, "form": f["form"], "filed": f["filed"], "accession": f["accession"]})
                        if cover is None:
                            item["why"] = "no cover-page shares in the filing"
                        else:
                            item.update({"shares_as_of": str(cover["as_of"]), "classes": cover["classes"], "shares": MV.priced_shares(r.symbol, cover)})
                            sp = splits.get(r.symbol)
                            if sp and str(sp) > str(cover["as_of"]):
                                item["split_after_cover"] = str(sp)
                            if item["close"]:
                                item["computed"] = item["shares"] * item["close"]
                                if item["vendor"]:
                                    item["diff_pct"] = round((item["computed"] / item["vendor"] - 1) * 100, 2)
            except Exception as exc:                      # one company's failure is reported, never the run's
                item["why"] = f"error: {type(exc).__name__}: {str(exc)[:120]}"
            out.append(item)
            print(r.symbol, item.get("diff_pct", item.get("why")), flush=True)
    finally:
        await edgar.close()
    json.dump(out, open(out_path, "w"), indent=1, default=str)
    have = [o for o in out if "computed" in o]
    print(f"{len(have)} of {len(out)} computed; {sum(1 for o in have if abs(o.get('diff_pct', 0)) > DIFFERS_PCT)} differ from the vendor by more than {DIFFERS_PCT}%")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
