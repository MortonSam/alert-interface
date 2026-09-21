"""Summarise a backtest of Ivy's rule into the record that /ivy renders. Pure."""
from __future__ import annotations


def summarize(folds: list[dict]) -> dict:
    """folds: [{label, setups, hits, base_n, base_ups}] for the chosen cutoff, in time order.

    Overall rates are pooled (total hits / total setups, total ups / total
    events), not an average of fold rates. Rates keep 6 decimals so a page
    rounding to one decimal does not round twice (198/365 is 54.2%, not 54.3%).
    """
    out_folds = []
    for f in folds:
        out_folds.append({
            "label": f["label"],
            "setups": f["setups"],
            "hits": f["hits"],
            "hit_rate": round(f["hits"] / f["setups"], 6) if f["setups"] else None,
            "base_n": f["base_n"],
            "base_rate": round(f["base_ups"] / f["base_n"], 6) if f["base_n"] else None,
        })
    setups = sum(f["setups"] for f in folds)
    hits = sum(f["hits"] for f in folds)
    base_n = sum(f["base_n"] for f in folds)
    base_ups = sum(f["base_ups"] for f in folds)
    return {
        "folds": out_folds,
        "setups": setups,
        "hits": hits,
        "hit_rate": round(hits / setups, 6) if setups else 0.0,
        "base_n": base_n,
        "base_rate": round(base_ups / base_n, 6) if base_n else 0.0,
    }
