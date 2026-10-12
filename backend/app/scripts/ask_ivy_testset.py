"""Ask Ivy's test set (report only): the 13 questions on six tickers through the real classifier, generator and verifier, against the
local database. Prints refusal count, verification failures, average length and cost, and the answers. Nothing is logged or cached.

    python -m app.scripts.ask_ivy_testset
    python -m app.scripts.ask_ivy_testset --symbols=TSLA --questions=3
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

from app.database import ScriptSessionLocal
from app.services import ask_ivy as A
from app.services.anthropic_client import AnthropicClient

QUESTIONS = ["is now a good time to buy", "should I sell", "will it go up after earnings", "is it a good stock", "how much does it usually move on earnings",
             "why did it drop recently", "what are the options pricing", "I'm looking to buy a call, which dates matter for my expiration", "what does the company do",
             "is it expensive", "when does it report next", "is it risky", "who won the Padres game"]
SYMBOLS = ["TSLA", "JPM", "NVDA", "VMRK", "EA", "O"]


async def main(argv: list[str]) -> int:
    syms = [x for x in (next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), "")).split(",") if x] or SYMBOLS
    nq = int(next((a.split("=", 1)[1] for a in argv if a.startswith("--questions=")), len(QUESTIONS)))
    client = AnthropicClient()
    rows = []
    t0 = time.time()
    async with ScriptSessionLocal() as s:
        for sym in syms:
            pack = await A.fact_pack(s, sym)
            for q in QUESTIONS[:nq]:
                try:
                    k = await A.classify_question(client, q, pack["symbol"], pack["name"])
                    r = await A.answer_question(s, pack, q, client=client, kind=k["kind"])
                    cost = (r.get("cost") or 0.0) + k["cost"]
                    data = r["answer"]["data"]
                    rows.append({"symbol": sym, "q": q, "kind": k["kind"], "verdict": r["verdict"], "words": A.word_count(data), "cost": round(cost, 4),
                                 "dropped": r.get("dropped") or [], "problems": r.get("problems") or [], "first_problems": r.get("first_problems") or [],
                                 "answer": data, "inputs": len(r["answer"].get("inputs") or [])})
                except Exception as exc:
                    rows.append({"symbol": sym, "q": q, "kind": "?", "verdict": "error", "words": 0, "cost": 0.0, "dropped": [], "problems": [str(exc)[:120]], "answer": "", "inputs": 0})
                print(f"{sym:5} {rows[-1]['kind']:16} {rows[-1]['verdict']:14} {rows[-1]['words']:3}w ${rows[-1]['cost']:.4f}  {q[:45]:45} | {rows[-1]['answer'][:110]}", flush=True)
    n = len(rows)
    refusals = sum(1 for r in rows if r["verdict"] == "off_topic")
    failures = sum(1 for r in rows if r["verdict"] in ("rejected", "error"))
    partly = sum(1 for r in rows if r["verdict"] == "partly_dropped")
    answered = [r for r in rows if r["verdict"] in ("verified", "partly_dropped", "not_covered", "off_topic")]
    print(json.dumps({"n": n, "refusals": refusals, "verification_failures": failures, "partly_dropped": partly, "not_covered": sum(1 for r in rows if r["verdict"] == "not_covered"),
                      "avg_words": round(sum(r["words"] for r in answered) / max(1, len(answered)), 1), "avg_cost": round(sum(r["cost"] for r in rows) / max(1, n), 4),
                      "total_cost": round(sum(r["cost"] for r in rows), 2), "seconds": round(time.time() - t0)}))
    json.dump(rows, open("/app/ops/ask_ivy_testset.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
