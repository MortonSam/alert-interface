"""An options read that does not exist carries no timestamp: the reason is the whole answer."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.options import OptionsReadRead


@pytest.mark.asyncio
async def test_absent_read_has_null_generated_at_and_as_of():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/tickers/options-read/ZZNOCHAIN")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False and body["reason"]
    assert body["generated_at"] is None and body["as_of"] is None
    assert body["model_used"] == "none" and body["content"] == ""


def test_schema_allows_null_timestamps_only_with_a_reason_path():
    read = OptionsReadRead(symbol="X", content="", facts={}, model_used="none", generated_at=None, cached=False,
                           as_of=None, available=False, reason="no chain")
    assert read.generated_at is None and read.as_of is None


def test_no_request_time_stamp_in_the_options_read_endpoint():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "app" / "routers" / "tickers.py"
    text = src.read_text()
    body = text[text.index("def absent(reason: str"):]
    body = body[:body.index("\n@router.")]
    assert "as_of=as_of" not in body and "dt_datetime.now(tz=timezone.utc).isoformat()\n\n    def absent" not in body
    assert "as_of=generated_at" in body and "as_of=cached[\"generated_at\"]" in body
