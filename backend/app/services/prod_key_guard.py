"""A job against the production database runs with production's own environment, and so production's Anthropic key, never the
Mac's dev key (2026-10-20: a production seed_release_eps run from the Mac used the dev key, hit its workspace limit and stored 13 of
39 reports). Production's environment is the one Railway supplies, on the platform or through `railway run --service alert-interface`
(backend/ops/prod_run.sh), and Railway sets RAILWAY_ENVIRONMENT_NAME=production in it; the dev .env does not.

    is_production_db(url)          -> True for production's database (Railway's internal host or its public proxy)
    check_production_key(url, env) -> raises DevKeyOnProduction for production's database without production's environment
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

PRODUCTION_DB_HOSTS = ("postgres.railway.internal", ".proxy.rlwy.net")


class DevKeyOnProduction(RuntimeError):
    pass


def is_production_db(url: str | None) -> bool:
    host = (urlsplit(url or "").hostname or "").lower()
    return any(host == h or (h.startswith(".") and host.endswith(h)) for h in PRODUCTION_DB_HOSTS)


def check_production_key(url: str | None = None, env: Mapping[str, str] | None = None) -> None:
    from app.config import settings
    env = os.environ if env is None else env
    url = settings.database_url if url is None else url
    if is_production_db(url) and env.get("RAILWAY_ENVIRONMENT_NAME") != "production":
        raise DevKeyOnProduction(
            "refused: this job reads or writes production's database without production's environment, so its Anthropic key is "
            "not production's. Run it with backend/ops/prod_run.sh (railway run --service alert-interface).")
