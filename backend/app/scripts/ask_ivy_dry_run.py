"""Ask Ivy dry run: answer questions about one stock exactly as the endpoint would, printing the fact pack size, the model's
raw output, the output-check and comparison problems, the verifier's verdicts, the rendered answer and the estimated cost.
Charges no limit and writes nothing (no ask_log row, no spend).

    python -m app.scripts.ask_ivy_dry_run MU "Is Micron expensive right now?" "How did it react to the last report?"
    python -m app.scripts.ask_ivy_dry_run MU --facts          # print the fact pack only
"""
from __future__ import annotations

import asyncio
import json
import sys

from app.database import ScriptSessionLocal
from app.services import ask_ivy as A


async def run(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__); return 2
    sym = args[0].upper()
    async with ScriptSessionLocal() as db:
        pack = await A.fact_pack(db, sym)
        print(f"{pack['symbol']} ({pack['name']}): {len(pack['facts'])} fact(s), fingerprint {pack['fingerprint']}, active={pack['active']}")
        if "--facts" in argv or len(args) == 1:
            for f in pack["facts"]:
                print(f"  {{fact:{f['id']}}} = {f['name']}: {f['value']} (as of {f['as_of']}) [{f['kind']}]")
            return 0
        total = 0.0
        for q in args[1:]:
            r = await A.answer_question(db, pack, q)
            total += r.get("cost") or 0.0
            print(f"\nQ: {q}")
            print(f"  model output: {json.dumps(r['raw'])}")
            print(f"  covered: {r['covered']}  verdict: {r['verdict']}  tokens {r['input_tokens']} in / {r['output_tokens']} out  est. ${r.get('cost', 0):.4f}")
            if r.get("problems"):
                print(f"  problems: {r['problems']}")
            if r.get("verifier"):
                for v in r["verifier"]:
                    print(f"  verifier: {v.get('status'):12s} {v.get('text', '')[:100]}")
            if r.get("dropped"):
                print(f"  dropped: {r['dropped']}")
            print(f"  ANSWER: {r['answer']['data']}")
            for i in r["answer"]["inputs"]:
                print(f"    receipt: {i['name']} = {i['value']} (as of {i['as_of']}; {i['source']})")
        print(f"\nestimated total ${total:.4f} for {len(args) - 1} question(s)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
