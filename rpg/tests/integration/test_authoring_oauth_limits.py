"""OAuth limits honor trusted proxies and share counters across processes."""
import os
import re
import shutil
import subprocess
import sys
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from platform_app.authoring.oauth import _limited


def request(peer, forwarded=""):
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "method": "POST", "path": "/oauth/authoring/register",
                    "headers": headers, "client": (peer, 1234), "server": ("example.com", 443),
                    "scheme": "https", "query_string": b""})


def test_proxy_client_limits_ignore_forged_forwarded_addresses(monkeypatch):
    monkeypatch.setenv("RPG_TRUSTED_PROXIES", "10.0.0.0/8")
    counts = {}

    def shared_counter(key, seconds):
        assert seconds == 60
        counts[key] = counts.get(key, 0) + 1
        return counts[key]

    monkeypatch.setattr("redis_bus.rate_incr", shared_counter)
    # The trusted chain chooses the rightmost untrusted hop, not an attacker-supplied prefix.
    _limited(request("10.0.0.4", "203.0.113.99, 192.0.2.10, 10.0.0.3"), "register", 1)
    with pytest.raises(HTTPException) as error:
        _limited(request("10.0.0.4", "203.0.113.98, 192.0.2.10"), "register", 1)
    assert error.value.status_code == 429
    # A different real client through the same proxy has its own window.
    _limited(request("10.0.0.4", "192.0.2.11"), "register", 1)
    # An untrusted peer cannot choose its rate-limit identity with XFF.
    _limited(request("192.0.2.30", "192.0.2.31"), "register", 1)
    with pytest.raises(HTTPException) as error:
        _limited(request("192.0.2.30", "192.0.2.32"), "register", 1)
    assert error.value.status_code == 429


@pytest.mark.skipif(os.getenv("RPG_REDIS_DOCKER_TEST") != "1" or not shutil.which("docker"),
                    reason="requires opt-in and local Docker Redis image")
def test_rate_limit_is_shared_by_independent_workers():
    container = subprocess.check_output([
        "docker", "run", "--rm", "-d", "-p", "127.0.0.1::6379", "redis:7-alpine",
        "redis-server", "--save", "", "--appendonly", "no",
    ], text=True).strip()
    try:
        mapped = subprocess.check_output(["docker", "port", container, "6379/tcp"], text=True).strip()
        port = int(re.search(r":(\d+)$", mapped).group(1))
        for _ in range(30):
            if subprocess.run(["docker", "exec", container, "redis-cli", "ping"],
                              capture_output=True).returncode == 0:
                break
            time.sleep(0.1)
        env = {**os.environ, "REDIS_URL": f"redis://127.0.0.1:{port}/0", "RPG_TRUSTED_PROXIES": ""}
        worker = """
from fastapi import HTTPException
from starlette.requests import Request
from platform_app.authoring.oauth import _limited
request = Request({'type':'http', 'method':'POST', 'path':'/', 'headers':[],
                   'client':('192.0.2.45', 1234), 'server':('example.com',443),
                   'scheme':'https', 'query_string':b''})
try:
    _limited(request, 'register', 2)
    print('allowed')
except HTTPException as exc:
    print(exc.status_code)
"""
        results = [subprocess.check_output([sys.executable, "-c", worker], env=env, text=True).strip()
                   for _ in range(3)]
        assert results == ["allowed", "allowed", "429"]
    finally:
        subprocess.run(["docker", "stop", container], check=False, capture_output=True)
