"""services/prod_key_guard: a job on production's database runs only with production's environment (and so its Anthropic key)."""
import pytest

from app.services.prod_key_guard import DevKeyOnProduction, check_production_key, is_production_db

PROD_PUBLIC = "postgresql+asyncpg://postgres:x@hayabusa.proxy.rlwy.net:41234/railway"
PROD_INTERNAL = "postgresql+asyncpg://postgres:x@postgres.railway.internal:5432/railway"
DEV = "postgresql+asyncpg://alert:alert@db:5432/alertdb"


def test_production_hosts():
    assert is_production_db(PROD_PUBLIC) and is_production_db(PROD_INTERNAL)
    assert not is_production_db(DEV) and not is_production_db("postgresql://alert:alert@localhost:5432/alertdb_test")
    assert not is_production_db("postgresql://u:p@notproxy.rlwy.net.example.com/x") and not is_production_db(None)


def test_refuses_production_with_the_dev_environment():
    with pytest.raises(DevKeyOnProduction):
        check_production_key(PROD_PUBLIC, {})                                         # the Mac's .env: no Railway environment
    with pytest.raises(DevKeyOnProduction):
        check_production_key(PROD_PUBLIC, {"RAILWAY_ENVIRONMENT_NAME": "staging"})


def test_allows_production_with_its_environment_and_dev_with_any():
    check_production_key(PROD_PUBLIC, {"RAILWAY_ENVIRONMENT_NAME": "production"})       # railway run --service alert-interface
    check_production_key(PROD_INTERNAL, {"RAILWAY_ENVIRONMENT_NAME": "production"})     # on the platform
    check_production_key(DEV, {})


def test_the_client_runs_the_guard(monkeypatch):
    from app.config import settings
    from app.services.anthropic_client import AnthropicClient
    monkeypatch.setattr(settings, "database_url", PROD_PUBLIC)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    with pytest.raises(DevKeyOnProduction):
        AnthropicClient()
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    AnthropicClient()


@pytest.mark.asyncio
async def test_a_dev_key_failure_never_writes_production_records(monkeypatch):
    """2026-10-20: billing failures from a Mac run on the dev key landed in production's ai_api_failures and ai_api_last_serious."""
    from app.config import settings
    from app.services import ai_health
    monkeypatch.setattr(settings, "database_url", PROD_PUBLIC)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    opened = []
    import app.database
    monkeypatch.setattr(app.database, "ScriptSessionLocal", lambda: opened.append(1))
    sent = []
    import app.services.notify
    async def fake_notify(*a, **k):
        sent.append(a)
    monkeypatch.setattr(app.services.notify, "notify", fake_notify)
    entry = await ai_health.record_failure("read_release_eps", RuntimeError("You have reached your specified workspace API usage limits"))
    assert entry["kind"] == "billing" and opened == [] and sent == []
