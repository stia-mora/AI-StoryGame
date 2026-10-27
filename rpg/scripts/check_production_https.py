"""Disposable production-mode HTTPS smoke test; never uses the user's DB or .env.

Run: python scripts/check_production_https.py [application-image]
Requires Docker, openssl and local postgres:17-alpine/nginx:stable-alpine images.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(*args, check=True):
    result = subprocess.run(args, check=False, text=True, encoding="utf-8", errors="replace",
                            capture_output=True, creationflags=FLAGS)
    if check and result.returncode:
        raise RuntimeError(f"{args[0]} {args[1]} failed (exit {result.returncode})")
    return result


def location(source, declaration):
    start = source.index(declaration)
    opening = source.index("{", start)
    depth = 1
    for index in range(opening + 1, len(source)):
        depth += (source[index] == "{") - (source[index] == "}")
        if not depth:
            return source[start:index + 1]
    raise ValueError("Unclosed documented nginx location")


def request(url, context, method="GET", data=None, headers=None):
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, response_headers, newurl):
            return None

    try:
        response = build_opener(HTTPSHandler(context=context), NoRedirect()).open(
            Request(url, data=data, method=method, headers=headers or {}), timeout=3)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, response.headers, response.read()


def main():
    image = sys.argv[1] if len(sys.argv) > 1 else "ai-storygame:creator-readiness-local"
    prefix = "creator-https-smoke-" + uuid.uuid4().hex[:12]
    network, pg, backend, nginx = (prefix + suffix for suffix in ("-net", "-pg", "-app", "-nginx"))
    # Reserve a loopback port only. Docker will fail safely if another process takes it.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"https://127.0.0.1:{port}"
    password, master, email = (secrets.token_hex(32) for _ in range(3))
    env = {
        "DATABASE_URL": f"postgresql://smoke:{password}@db:5432/smoke",
        "RPG_ENV": "prod", "RPG_DEPLOYMENT_MODE": "server", "RPG_REQUIRE_AUTH": "1",
        "RPG_SKIP_AUTO_MIGRATE": "1", "RPG_FEDERATION_PROVIDER": "1",
        "RPG_MASTER_KEY": master, "EMAIL_CODE_SECRET": email,
        "PUBLIC_BASE_URL": base, "RPG_CORS_ORIGINS": base,
        "RPG_DATA_ROOT": "/tmp/creator-smoke-data", "RPG_WORKERS": "1",
        "RPG_TRUSTED_PROXIES": "172.16.0.0/12", "RPG_POSTPROC_MODE": "inline",
    }
    env_args = [argument for key, value in env.items() for argument in ("-e", f"{key}={value}")]
    with tempfile.TemporaryDirectory(prefix="creator-https-smoke-") as directory:
        temp = Path(directory)
        cert, key, config = temp / "cert.pem", temp / "key.pem", temp / "nginx.conf"
        openssl_config = temp / "openssl.cnf"
        openssl_config.write_text("[req]\ndistinguished_name = dn\n[dn]\n", encoding="ascii")
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-keyout", str(key), "-out", str(cert), "-subj", "/CN=127.0.0.1",
            "-config", str(openssl_config), "-addext", "subjectAltName=IP:127.0.0.1")
        source = (ROOT / "deploy/bare-metal/README.md").read_text(encoding="utf-8")
        route = location(source, "location ~ ^/(mcp/authoring")
        route = route.replace("http://127.0.0.1:7860", "http://backend:7860")
        config.write_text("events { worker_connections 64; }\nhttp { server { listen 443 ssl; "
                          "ssl_certificate /tmp/cert.pem; ssl_certificate_key /tmp/key.pem; "
                          "location = /readyz { proxy_pass http://backend:7860; } " + route + " } }\n",
                          encoding="utf-8")
        try:
            run("docker", "network", "create", network)
            run("docker", "run", "-d", "--name", pg, "--network", network, "--network-alias", "db",
                "-e", "POSTGRES_USER=smoke", "-e", "POSTGRES_DB=smoke",
                "-e", f"POSTGRES_PASSWORD={password}", "postgres:17-alpine")
            for _ in range(60):
                if run("docker", "exec", pg, "pg_isready", "-U", "smoke", "-d", "smoke", check=False).returncode == 0:
                    break
                time.sleep(.5)
            else:
                raise RuntimeError("Disposable PostgreSQL did not become ready")
            run("docker", "run", "--rm", "--network", network, *env_args, "--entrypoint", "python",
                image, "-m", "platform_app.migrate", "full")
            run("docker", "run", "-d", "--name", backend, "--network", network, "--network-alias", "backend",
                *env_args, image)
            run("docker", "run", "-d", "--name", nginx, "--network", network,
                "-p", f"127.0.0.1:{port}:443",
                "--mount", f"type=bind,source={config},target=/etc/nginx/nginx.conf,readonly",
                "--mount", f"type=bind,source={cert},target=/tmp/cert.pem,readonly",
                "--mount", f"type=bind,source={key},target=/tmp/key.pem,readonly", "nginx:stable-alpine")
            context = ssl.create_default_context(cafile=str(cert))
            for _ in range(90):
                try:
                    status, _, _ = request(base + "/readyz", context)
                    if status == 200:
                        break
                except (OSError, URLError):
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("Production HTTPS endpoint did not become ready")
            for path in ("/.well-known/oauth-protected-resource/mcp/authoring",
                         "/.well-known/oauth-authorization-server"):
                status, headers, raw = request(base + path, context)
                payload = json.loads(raw)
                assert status == 200 and headers.get_content_type() == "application/json"
                assert payload.get("resource", base + "/mcp/authoring") == base + "/mcp/authoring"
                assert payload.get("issuer", base) == base
                print(path + ": 200 JSON, HTTPS origin verified")
            registration = json.dumps({"client_name": "Smoke client", "redirect_uris": ["http://127.0.0.1:48321/callback"]}).encode()
            status, _, raw = request(base + "/oauth/authoring/register", context, "POST", registration,
                                     {"Content-Type": "application/json"})
            client_id = json.loads(raw)["client_id"]
            assert status == 201 and client_id.startswith("authoring_")
            print("OAuth dynamic client registration: 201")
            status, headers, _ = request(base + "/mcp/authoring", context, "POST",
                                         b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
                                         {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
            assert status == 401 and "bearer" in headers.get("WWW-Authenticate", "").lower()
            print("Unauthenticated MCP initialize: 401 Bearer challenge")
            # Seed only the disposable database and use a real account session.
            seed = ("from platform_app.db import connect; from platform_app.auth import _issue_session; "
                    "db=connect(); c=db.__enter__(); "
                    "u=c.execute(\"insert into users(username,password_hash,display_name,account_mode,email_verified) "
                    "values('smoke_creator','test','Smoke','creator',true) returning id\").fetchone(); "
                    "print(_issue_session(c,u['id'])); db.__exit__(None,None,None)")
            session = run("docker", "exec", backend, "python", "-c", seed).stdout.strip().splitlines()[-1]
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            redirect = "http://127.0.0.1:48321/callback"
            params = dict(client_id=client_id, redirect_uri=redirect, scope="authoring:read",
                          response_type="code", code_challenge_method="S256", code_challenge=challenge,
                          resource=base + "/mcp/authoring", state="smoke")
            cookie = {"Cookie": "rpg_session=" + session}
            status, _, raw = request(base + "/oauth/authoring/authorize?" + urlencode(params), context, headers=cookie)
            assert status == 200
            page = raw.decode()
            request_id = re.search(r"name='request_id' value='([^']+)'", page).group(1)
            csrf = re.search(r"name='csrf' value='([^']+)'", page).group(1)
            form = urlencode(dict(request_id=request_id, csrf=csrf, decision="allow")).encode()
            status, headers, _ = request(base + "/oauth/authoring/authorize", context, "POST", form,
                                         {**cookie, "Content-Type": "application/x-www-form-urlencoded"})
            assert status == 303
            query = parse_qs(urlsplit(headers["Location"]).query)
            assert query["state"] == ["smoke"]
            form = urlencode(dict(grant_type="authorization_code", client_id=client_id, code=query["code"][0],
                                  code_verifier=verifier, redirect_uri=redirect, resource=params["resource"])).encode()
            status, _, raw = request(base + "/oauth/authoring/token", context, "POST", form,
                                     {"Content-Type": "application/x-www-form-urlencoded"})
            assert status == 200
            token = json.loads(raw)["access_token"]
            mcp_headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json",
                           "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
            payload = dict(jsonrpc="2.0", id=2, method="tools/call",
                           params=dict(name="authoring_get_contract", arguments={}))
            status, headers, raw = request(base + "/mcp/authoring", context, "POST", json.dumps(payload).encode(), mcp_headers)
            if headers.get_content_type() == "text/event-stream":
                data = next(line[5:].strip() for line in raw.decode().splitlines() if line.startswith("data:"))
                result = json.loads(data)
            else:
                result = json.loads(raw)
            assert status == 200 and not result["result"].get("isError")
            assert result["result"]["structuredContent"]["version"] == 1
            print("Authenticated OAuth authorization and MCP contract call: passed")
            print("Production-mode HTTPS smoke passed with disposable PostgreSQL and nginx")
        finally:
            for name in (nginx, backend, pg):
                # -v removes only anonymous volumes attached to these exact containers.
                run("docker", "rm", "-f", "-v", name, check=False)
            run("docker", "network", "rm", network, check=False)


if __name__ == "__main__":
    main()
