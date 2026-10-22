import asyncio

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from core import request_limits
from core.production import validate
from platform_app.api._deps import _client_ip


def test_trusted_proxy_network_and_rightmost_client(monkeypatch):
    monkeypatch.setenv("RPG_TRUSTED_PROXIES", "127.0.0.1,172.16.0.0/12")
    def client(peer, chain):
        return _client_ip(Request({"type": "http", "client": (peer, 123), "headers": [(b"x-forwarded-for", chain.encode())]}))
    assert client("172.18.0.5", "198.51.100.1") == "198.51.100.1"
    assert client("172.18.0.5", "198.51.100.2") == "198.51.100.2"
    assert client("172.18.0.5", "1.2.3.4, 198.51.100.2, 172.18.0.6") == "198.51.100.2"
    assert client("198.51.100.3", "1.2.3.4") == "198.51.100.3"
    assert client("172.18.0.5", "bad-ip") == "172.18.0.5"


def test_production_fails_closed_without_shared_secrets_or_auth(monkeypatch):
    monkeypatch.setenv("RPG_DEPLOYMENT_MODE", "server")
    monkeypatch.setenv("RPG_REQUIRE_AUTH", "0")
    with pytest.raises(RuntimeError, match="RPG_REQUIRE_AUTH"):
        validate()
    monkeypatch.setenv("RPG_REQUIRE_AUTH", "1")
    monkeypatch.delenv("EMAIL_CODE_SECRET", raising=False)
    monkeypatch.setenv("RPG_MASTER_KEY", "a" * 64)
    with pytest.raises(RuntimeError, match="EMAIL_CODE_SECRET"):
        validate()
    monkeypatch.setenv("EMAIL_CODE_SECRET", "b" * 64)
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://example.test")
    with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL"):
        validate()
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.setenv("RPG_CORS_ORIGINS", "https://example.test")
    validate()


def test_generic_rate_body_and_timeout_limits(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr("redis_bus.rate_incr", lambda *a: None)
    request_limits._windows.clear()
    monkeypatch.setenv("RPG_RATE_LIMIT_PER_MIN", "1")
    monkeypatch.setenv("RPG_BODY_LIMIT_BYTES", "1024")
    monkeypatch.setenv("RPG_UPLOAD_BODY_LIMIT_BYTES", "2048")
    async def request(body, headers=None, peer="198.51.100.1", delay=0):
        async def receive():
            await asyncio.sleep(delay)
            return {"type": "http.request", "body": body, "more_body": False}
        return Request({"type": "http", "method": "POST", "client": (peer, 1), "headers": headers or []}, receive)
    async def run():
        await request_limits.check(await request(b"ok"))
        with pytest.raises(HTTPException) as rate:
            await request_limits.check(await request(b"ok"))
        assert rate.value.status_code == 429
        with pytest.raises(HTTPException) as size:
            await request_limits.check(await request(b"x" * 1025, peer="198.51.100.2"))
        assert size.value.status_code == 413
        await request_limits.check(await request(b"x" * 1500, headers=[(b"content-type", b"application/octet-stream")], peer="198.51.100.4"))
        monkeypatch.setenv("RPG_REQUEST_TIMEOUT_SECS", "0.001")
        with pytest.raises(TimeoutError):
            await request_limits.check(await request(b"ok", peer="198.51.100.3", delay=.02))
    asyncio.run(run())


def test_response_header_timeout_does_not_cut_started_stream(monkeypatch):
    from core.startup import api_contract_middleware
    from fastapi.responses import StreamingResponse
    monkeypatch.setenv("RPG_REQUEST_TIMEOUT_SECS", "0.001")
    async def run():
        def request():
            return Request({"type": "http", "method": "GET", "path": "/api/health", "headers": []})
        async def slow(_):
            await asyncio.sleep(.02)
        response = await api_contract_middleware(request(), slow)
        assert response.status_code == 504
        async def content():
            yield "start"
            await asyncio.sleep(.02)
            yield "finish"
        async def stream(_):
            return StreamingResponse(content(), media_type="text/event-stream")
        response = await api_contract_middleware(request(), stream)
        assert response.status_code == 200
        assert [chunk async for chunk in response.body_iterator] == ["start", "finish"]
    asyncio.run(run())
