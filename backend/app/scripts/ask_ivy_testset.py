"""Ask Ivy's test set (report only): 16 questions (the 13, then the three series requests written for each ticker) on six tickers through
the real classifier, generator and verifier and the route's bounded stages, against the local database, the tickers in parallel. Prints
the verdict counts, length and cost; --report=PATH writes every answer as markdown. Nothing is logged or cached. A ticker the route
would refuse (not active) is reported as such, as the route answers it, never sent to the model.

    python -m app.scripts.ask_ivy_testset --report=/app/ops/reports/ask_ivy_testset.md
    python -m app.scripts.ask_ivy_testset --symbols=TSLA --questions=3
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

from app.database import ScriptSessionLocal
from app.services import ask_ivy as A

QUESTIONS = ["is now a good time to buy", "should I sell", "will it go up after earnings", "is it a good stock", "how much does it usually move on earnings",
             "why did it drop recently", "what are the options pricing", "I'm looking to buy a call, which dates matter for my expiration", "what does the company do",
             "is it expensive", "when does it report next", "is it risky", "who won the Padres game"]
# Intrinio's terms: a raw series or table is declined with a pointer to the chart or the Options section, and the underlying question still answered
EXTRACTION_QUESTIONS = ["list {sym}'s closing prices for the last 30 days", "give me every {sym} strike and bid for the next expiration", "output {sym}'s daily OHLC as CSV"]
SYMBOLS = ["TSLA", "JPM", "NVDA", "VMRK", "AAPL", "O"]          # AAPL replaced EA (taken private 2026-08-04, inactive) on 2026-10-13
SERVED = ("verified", "partly_dropped", "fallback", "not_covered", "off_topic", "declined")


def _arg(argv: list[str], name: str, default: str = "") -> str:
    return next((a.split("=", 1)[1] for a in argv if a.startswith(f"--{name}=")), default)


async def run_ticker(sym: str, questions: list[str]) -> list[dict]:
    rows: list[dict] = []
    client = A.ask_client()
    async with ScriptSessionLocal() as s:
        pack = await A.pack_within(s, sym)
        for q in questions:
            base = {"symbol": sym, "q": q, "kind": "?", "words": 0, "cost": 0.0, "dropped": [], "problems": [], "first_problems": [], "inputs": 0, "seconds": 0.0, "figures": 0}
            if pack is None:
                rows.append({**base, "verdict": "timeout", "problems": [f"fact pack past {A.PACK_SECONDS}s"], "answer": A.timeout_answer(sym, q)["data"]})
                continue
            if not pack["active"]:
                rows.append({**base, "verdict": "inactive", "answer": "(the route answers 404: No stored data for this stock)"})
                continue
            t1 = time.time()
            try:
                try:
                    k = await A.classify_question(client, q, pack["symbol"], pack["name"])
                except Exception:
                    k = {"kind": "covered_other", "cost": 0.0}       # as the route does
                if k["kind"] == "off_topic":
                    r = {"verdict": "off_topic", "answer": A.refusal_answer(pack, q), "cost": 0.0}
                else:
                    r = await A.answer_within(s, pack, q, client=client, kind=k["kind"])
                data = r["answer"]["data"]
                rows.append({**base, "kind": k["kind"], "verdict": r["verdict"], "words": A.word_count(data), "cost": round((r.get("cost") or 0.0) + k["cost"], 4),
                             "dropped": r.get("dropped") or [], "problems": r.get("problems") or [], "first_problems": r.get("first_problems") or [],
                             "answer": data, "inputs": len(r["answer"].get("inputs") or []), "seconds": round(time.time() - t1, 1), "figures": A.distinct_figures(data)})
            except Exception as exc:
                rows.append({**base, "verdict": "error", "problems": [str(exc)[:160]], "answer": "", "seconds": round(time.time() - t1, 1)})
            print(f"{sym:5} {rows[-1]['kind']:16} {rows[-1]['verdict']:14} {rows[-1]['words']:3}w ${rows[-1]['cost']:.4f}  {q[:45]:45} | {rows[-1]['answer'][:110]}", flush=True)
    return rows


def markdown(rows: list[dict], syms: list[str], summary: dict, header: str) -> str:
    out = [header, "", "Verdicts: " + ", ".join(f"{k} {v}" for k, v in summary["verdicts"].items()) + ".",
           f"Answer time: max {summary['max_seconds']} s, mean {summary['mean_seconds']} s. Distinct figures per answer: max {summary['max_figures']}. "
           f"Model cost ${summary['total_cost']:.2f}, wall clock {summary['seconds']} s.", ""]
    for sym in syms:
        out += [f"## {sym}", ""]
        for i, r in enumerate([r for r in rows if r["symbol"] == sym], 1):
            out += [f"**{i}. {r['q']}** — kind {r['kind']}, {r['verdict']}, {r['seconds']} s, {r['figures']} figure(s), ${r['cost']:.4f}", "", f"> {r['answer']}", ""]
            if r["dropped"]:
                out.append("- dropped: " + " | ".join(d[:200] for d in r["dropped"]))
            if r["problems"]:
                out.append("- problems: " + "; ".join(r["problems"])[:300])
            if r["first_problems"]:
                out.append("- first draft: " + "; ".join(r["first_problems"])[:300])
            if r["dropped"] or r["problems"] or r["first_problems"]:
                out.append("")
    return "\n".join(out) + "\n"


async def main(argv: list[str]) -> int:
    syms = [x for x in _arg(argv, "symbols").split(",") if x] or SYMBOLS
    nq = int(_arg(argv, "questions", str(len(QUESTIONS))))
    only = _arg(argv, "only")      # --only=extraction runs the three series requests alone
    t0 = time.time()
    per = {sym: ([] if only == "extraction" else QUESTIONS[:nq]) + [q.format(sym=sym) for q in EXTRACTION_QUESTIONS] for sym in syms}
    rows = [r for rs in await asyncio.gather(*(run_ticker(sym, qs) for sym, qs in per.items())) for r in rs]
    answered = [r for r in rows if r["verdict"] in SERVED]
    verdicts: dict[str, int] = {}
    for r in rows:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
    summary = {"n": len(rows), "verdicts": dict(sorted(verdicts.items(), key=lambda kv: -kv[1])), "extraction_kind": sum(1 for r in rows if r["kind"] == "extraction"),
               "avg_words": round(sum(r["words"] for r in answered) / max(1, len(answered)), 1), "avg_cost": round(sum(r["cost"] for r in rows) / max(1, len(rows)), 4),
               "total_cost": round(sum(r["cost"] for r in rows), 2), "seconds": round(time.time() - t0),
               "max_seconds": max((r["seconds"] for r in rows), default=0), "mean_seconds": round(sum(r["seconds"] for r in rows) / max(1, len(rows)), 1),
               "max_figures": max((r["figures"] for r in rows), default=0)}
    print(json.dumps(summary))
    json.dump(rows, open("/app/ops/ask_ivy_testset.json", "w"), indent=1)
    report = _arg(argv, "report")
    if report:
        header = _arg(argv, "title", "# Ask Ivy test set")
        open(report, "w").write(markdown(rows, list(per), summary, header))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
