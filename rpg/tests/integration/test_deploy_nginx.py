"""Exercise the documented nginx locations with a local disposable nginx container.

Opt in with RPG_NGINX_DOCKER_TEST=1 and a local nginx:stable-alpine image.
The upstream is an in-container stub; no external service or credentials are used.
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(
    os.environ.get("RPG_NGINX_DOCKER_TEST") != "1" or not shutil.which("docker"),
    reason="requires opt-in and local Docker nginx image",
)


def location(source, declaration):
    """Extract the exact documented location block, including nested braces."""
    start = source.index(declaration)
    opening = source.index("{", start)
    depth = 1
    for index in range(opening + 1, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if not depth:
                return source[start:index + 1]
    raise AssertionError(f"unclosed nginx location: {declaration}")


def response(url, authorization=None):
    request = Request(url, headers={"Authorization": authorization} if authorization else {})
    try:
        result = urlopen(request, timeout=5)
    except HTTPError as exc:
        result = exc
    with result:
        return result.status, result.headers, result.read().decode()


@pytest.mark.parametrize("deployment", ["bare-metal", "test-server"])
def test_nginx_routes_mcp_and_keeps_private_media_out_of_public_cache(tmp_path, deployment):
    if deployment == "bare-metal":
        source = (ROOT / "deploy/bare-metal/README.md").read_text(encoding="utf-8")
        declarations = ["location / {", "location /api/ {", "location ~ ^/(mcp/authoring"]
    else:
        source = (ROOT / "deploy/test-server/nginx-rpg-roleplay.conf").read_text(encoding="utf-8")
        declarations = ["location / {", "location ^~ /assets/ {"]
    locations = "\n".join(location(source, name) for name in declarations)
    locations = locations.replace("http://backend:7860", "http://127.0.0.1:7860")
    # A real temporary nginx uses a stub upstream, not the user's application or data.
    config = f"""
events {{ worker_connections 64; }}
http {{
    server {{
        listen 127.0.0.1:7860;
        location ^~ /api/ {{
            add_header Cache-Control "private, no-store" always;
            if ($http_authorization = "") {{ return 403; }}
            return 200 "private-media";
        }}
        location / {{ return 200 "upstream:$uri|$http_host"; }}
    }}
    server {{ listen 8080; root /tmp; {locations} }}
}}
"""
    config_file = tmp_path / "nginx.conf"
    config_file.write_text(config, encoding="utf-8")
    container = subprocess.check_output([
        "docker", "run", "--rm", "-d", "-p", "127.0.0.1::8080",
        "--mount", f"type=bind,source={config_file},target=/etc/nginx/nginx.conf,readonly",
        "nginx:stable-alpine",
    ], text=True).strip()
    try:
        mapped = subprocess.check_output(["docker", "port", container, "8080/tcp"], text=True).strip()
        port = int(re.search(r":(\d+)$", mapped).group(1))
        base = f"http://127.0.0.1:{port}"
        for _ in range(30):
            try:
                response(base + "/mcp/authoring")
                break
            except OSError:
                time.sleep(0.1)
        for path in ("/mcp/authoring", "/.well-known/oauth-authorization-server", "/oauth/authoring/token"):
            status, _, body = response(base + path)
            assert status == 200 and body == f"upstream:{path}|127.0.0.1:{port}"
        path = "/api/storage/authoring/42/private.png"
        assert response(base + path)[0] == 403
        status, headers, body = response(base + path, "Bearer test-only")
        assert status == 200 and body == "private-media"
        cache = ",".join(headers.get_all("Cache-Control", []))
        assert "no-store" in cache and "public" not in cache and "immutable" not in cache
        if deployment == "test-server":
            status, headers, _ = response(base + "/assets/main-1234.js")
            assert status == 200 and "public" in ",".join(headers.get_all("Cache-Control", []))
    finally:
        subprocess.run(["docker", "stop", container], check=False, capture_output=True)
