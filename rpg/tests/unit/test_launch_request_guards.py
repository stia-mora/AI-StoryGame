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


def test_authoring_upload_is_not_buffered_before_authentication(monkeypatch):
    monkeypatch.setattr("redis_bus.rate_incr", lambda *args: None)
    request_limits._windows.clear()
    async def receive():
        raise AssertionError("middleware consumed the unauthenticated upload")
    request = Request({"type": "http", "method": "PUT",
                       "path": "/api/authoring/uploads/123/content",
                       "client": ("198.51.100.42", 1), "headers": []}, receive)
    asyncio.run(request_limits.check(request))


def test_buffered_uploads_are_bounded_and_release_slot_on_failure(monkeypatch):
    from core import startup
    from starlette.responses import Response

    async def run():
        entered, resume = asyncio.Event(), asyncio.Event()
        async def handler(_request, _call_next):
            entered.set()
            await resume.wait()
            raise RuntimeError("upload failed")
        monkeypatch.setattr(startup, "_api_contract_middleware", handler)
        def request():
            return Request({"type": "http", "method": "POST", "path": "/api/account/import",
                            "headers": [(b"content-type", b"application/zip")]})
        first = asyncio.create_task(startup.api_contract_middleware(request(), None))
        await entered.wait()
        denied = await startup.api_contract_middleware(request(), None)
        assert denied.status_code == 429
        assert denied.headers["retry-after"] == "30"
        resume.set()
        with pytest.raises(RuntimeError):
            await first
        async def success(_request, _call_next):
            return Response(status_code=204)
        monkeypatch.setattr(startup, "_api_contract_middleware", success)
        assert (await startup.api_contract_middleware(request(), None)).status_code == 204
    asyncio.run(run())


def test_one_failed_maintenance_task_does_not_stop_other_recovery(monkeypatch):
    from core.startup import _player_maintenance_once

    calls = []
    def fail():
        calls.append("reservation")
        raise RuntimeError("temporary failure")
    monkeypatch.setattr("platform_app.player.wallet.reap", fail)
    monkeypatch.setattr("platform_app.authoring.preview.reconcile", lambda: calls.append("preview"))
    monkeypatch.setattr("platform_app.authoring.service.recover", lambda: calls.append("import"))
    asyncio.run(_player_maintenance_once())
    assert calls == ["reservation", "preview", "import"]


def test_explicit_secure_cookie_configuration_is_enforced(monkeypatch):
    from platform_app.api._deps import _cookie_security_kwargs

    request = Request({"type": "http", "method": "POST", "path": "/api/auth/login",
                       "scheme": "http", "server": ("example.test", 80), "headers": []})
    monkeypatch.setenv("RPG_COOKIE_SECURE", "1")
    assert _cookie_security_kwargs(request)["secure"] is True
    monkeypatch.setenv("RPG_COOKIE_SECURE", "0")
    assert _cookie_security_kwargs(request)["secure"] is False
    https = Request({"type": "http", "method": "POST", "path": "/api/auth/login",
                     "scheme": "https", "server": ("example.test", 443), "headers": []})
    assert _cookie_security_kwargs(https)["secure"] is True


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


@pytest.mark.parametrize("path", ["/mcp/authoring", "/oauth/authoring/token"])
def test_mcp_and_oauth_apply_body_budget_to_chunked_requests(path, monkeypatch):
    from core.startup import api_contract_middleware

    monkeypatch.setenv("RPG_BODY_LIMIT_BYTES", "1024")
    monkeypatch.setattr("redis_bus.rate_incr", lambda *args: None)
    request_limits._windows.clear()
    chunks = iter([b"x" * 600, b"x" * 600])
    async def receive():
        chunk = next(chunks, b"")
        return {"type": "http.request", "body": chunk, "more_body": bool(chunk)}
    request = Request({"type": "http", "method": "POST", "path": path,
                       "client": ("198.51.100.44", 42), "headers": [(b"content-type", b"application/json")]}, receive)
    async def reached(_):
        raise AssertionError("oversized request reached the application")
    response = asyncio.run(api_contract_middleware(request, reached))
    assert response.status_code == 413
