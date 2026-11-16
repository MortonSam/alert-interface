"""Anthropic's own record of what the production key used (Sam, 2026-11-16), read with the Admin API: no model call.

Setting ANTHROPIC_ADMIN_KEY (an Admin API key, read only here). The production key is found among the organization's keys by its
partial hint (GET /v1/organizations/api_keys), and its tokens for a window by model come from the usage report
(GET /v1/organizations/usage_report/messages, hourly buckets, grouped by model). Priced with services/research_cost, the same table
the ledger uses, so the two figures differ only by calls the ledger never saw.
"""
from __future__ import annotations

from datetime import datetime

import httpx

BASE = "https://api.anthropic.com/v1/organizations"
VERSION = "2023-06-01"
TIMEOUT_SECONDS = 30.0
CACHE_1H_WRITE_MULTIPLIER = 2.0       # a one-hour cache entry is written at twice the input price


class UsageReportUnavailable(RuntimeError):
    """The Admin API could not be read, or the production key is not among the organization's keys."""


def _headers(admin_key: str) -> dict[str, str]:
    return {"x-api-key": admin_key, "anthropic-version": VERSION}


def hint_matches(hint: str | None, key: str) -> bool:
    """Pure: the console's partial hint ("sk-ant-api03-R2D...igAA") names this key."""
    if not hint or "..." not in hint or not key:
        return False
    head, tail = hint.split("...", 1)
    return key.startswith(head) and key.endswith(tail)


def priced(tokens_by_model: dict[str, dict[str, int]]) -> tuple[float, list[str]]:
    """Pure: the cost of {model: {in, cache_write, cache_write_1h, cache_read, out}} at research_cost's prices; the models with no
    price are returned apart (their tokens are not counted in the figure)."""
    from app.services.research_cost import CACHE_READ_MULTIPLIER, CACHE_WRITE_MULTIPLIER, PRICES_USD_PER_MTOK
    total, unpriced = 0.0, []
    for model, t in tokens_by_model.items():
        if model not in PRICES_USD_PER_MTOK:
            if any(t.values()):
                unpriced.append(model)
            continue
        pin, pout = PRICES_USD_PER_MTOK[model]
        total += (t.get("in", 0) * pin + t.get("out", 0) * pout + t.get("cache_write", 0) * pin * CACHE_WRITE_MULTIPLIER
                  + t.get("cache_write_1h", 0) * pin * CACHE_1H_WRITE_MULTIPLIER + t.get("cache_read", 0) * pin * CACHE_READ_MULTIPLIER) / 1_000_000
    return round(total, 4), unpriced


def tokens_from_report(pages: list[dict]) -> dict[str, dict[str, int]]:
    """Pure: the usage report's buckets summed by model into the ledger's kinds."""
    out: dict[str, dict[str, int]] = {}
    for page in pages:
        for bucket in page.get("data") or []:
            for r in bucket.get("results") or []:
                t = out.setdefault(r.get("model") or "unknown", {})
                cc = r.get("cache_creation") or {}
                for kind, n in (("in", r.get("uncached_input_tokens")), ("out", r.get("output_tokens")),
                                ("cache_read", r.get("cache_read_input_tokens")), ("cache_write", cc.get("ephemeral_5m_input_tokens")),
                                ("cache_write_1h", cc.get("ephemeral_1h_input_tokens"))):
                    t[kind] = t.get(kind, 0) + int(n or 0)
    return out


async def production_key_id(admin_key: str, api_key: str) -> str:
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as c:
        after = None
        while True:
            params = {"limit": 100, **({"after_id": after} if after else {})}
            r = await c.get(f"{BASE}/api_keys", headers=_headers(admin_key), params=params)
            if r.status_code != 200:
                raise UsageReportUnavailable(f"api_keys: HTTP {r.status_code}")
            body = r.json()
            for k in body.get("data") or []:
                if hint_matches(k.get("partial_key_hint"), api_key):
                    return k["id"]
            if not body.get("has_more"):
                raise UsageReportUnavailable("the production key is not among the organization's keys")
            after = body.get("last_id")


async def key_tokens(admin_key: str, key_id: str, start: datetime, end: datetime) -> dict[str, dict[str, int]]:
    """The key's tokens by model between `start` and `end` (aware datetimes; whole hours)."""
    pages, page = [], None
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as c:
        while True:
            params = {"starting_at": start.isoformat().replace("+00:00", "Z"), "ending_at": end.isoformat().replace("+00:00", "Z"),
                      "bucket_width": "1h", "group_by[]": "model", "api_key_ids[]": key_id, "limit": 168, **({"page": page} if page else {})}
            r = await c.get(f"{BASE}/usage_report/messages", headers=_headers(admin_key), params=params)
            if r.status_code != 200:
                raise UsageReportUnavailable(f"usage_report: HTTP {r.status_code}")
            body = r.json()
            pages.append(body)
            if not body.get("has_more"):
                return tokens_from_report(pages)
            page = body.get("next_page")
