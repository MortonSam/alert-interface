"""Rewrite every stored options chain (both sources) through the shared filter (services/chain_quality), once, for chains stored before
chain_store.put_chain applied it. Intrinio chains stored before the contract root was kept are cleaned by the quote rules and the
most-open-interest rule; the nightly Intrinio step re-reads them with their roots. Dry run by default: prints what each source would
lose; --write stores the cleaned chains.

Usage
-----
    python -m app.scripts.clean_stored_chains            # dry run
    python -m app.scripts.clean_stored_chains --write    # on Railway (a whole-table rewrite)
"""
from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import chain_store
from app.services.chain_quality import clean_chain

_SOURCE_OF_PREFIX = {"chain": chain_store.COURIER, "intrinio_chain": chain_store.INTRINIO}


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    totals = {src: {"chains": 0, "changed": 0, "nonstandard": 0, "duplicates": 0} for src in chain_store.SOURCES}
    tickers: dict[str, set[str]] = {src: set() for src in chain_store.SOURCES}
    async with ScriptSessionLocal() as s:
        keys = (await s.execute(text("SELECT key FROM system_metadata WHERE key LIKE 'chain:%:%' OR key LIKE 'intrinio_chain:%:%' ORDER BY key"))).scalars().all()
        for key in keys:
            prefix, sym, exp = key.split(":")
            source = _SOURCE_OF_PREFIX[prefix]
            raw = (await s.execute(text("SELECT value FROM system_metadata WHERE key = :k"), {"k": key})).scalar()
            try:
                chain = json.loads(raw)
            except (ValueError, TypeError):
                continue
            chain.setdefault("chain_source", source)            # a courier chain stored before the field existed
            totals[source]["chains"] += 1
            prior = chain.get("chain_quality") or {}
            cleaned = clean_chain(chain, sym)
            dropped_ns = cleaned["chain_quality"]["dropped_nonstandard"] - (prior.get("dropped_nonstandard") or 0)
            dropped_dup = cleaned["chain_quality"]["dropped_duplicates"] - (prior.get("dropped_duplicates") or 0)
            if "chain_quality" in chain and not (dropped_ns or dropped_dup):
                continue                                         # stored through the filter already, nothing to drop
            if dropped_ns or dropped_dup:
                totals[source]["changed"] += 1
                totals[source]["nonstandard"] += dropped_ns
                totals[source]["duplicates"] += dropped_dup
                tickers[source].add(sym)
            if write:
                await chain_store.put_chain(s, sym, exp, chain, source)
                await s.commit()
    for src in chain_store.SOURCES:
        t = totals[src]
        print(f"{src}: {t['chains']} chain(s), {t['changed']} with contracts removed ({t['nonstandard']} non-standard, {t['duplicates']} duplicate strike), "
              f"{len(tickers[src])} ticker(s): {', '.join(sorted(tickers[src])[:60])}{' ...' if len(tickers[src]) > 60 else ''}")
    print("written" if write else "dry run: nothing written (add --write, on Railway)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
