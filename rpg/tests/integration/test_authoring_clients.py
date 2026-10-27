"""Opt-in installed-client OAuth checks. No browser windows or user config writes."""
# ruff: noqa: F811 -- imported pytest fixtures are injected by name.
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest

from platform_app import auth
from platform_app.authoring import oauth
from platform_app.db import connect
from tests.integration.test_authoring import creator, isolated_database  # noqa: F401
from tests.integration.test_authoring_http import CLAUDE_TOOL_RESULTS

pytestmark = pytest.mark.skipif(os.getenv("AUTHORING_CLIENT_CHECKS") != "1", reason="Opt in with --clients")


def login_with_browser_session(command, env, cwd, session, base):
    use_pty = os.name == "nt" and "claude" in Path(command[0]).name.lower()
    if use_pty:
        from winpty import PtyProcess
        process = PtyProcess.spawn(command, cwd=str(cwd), env=env, dimensions=(40, 2000))
    else:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    messages = queue.Queue()
    def reader():
        try:
            while char := (process.read(1) if use_pty else process.stdout.read(1)):
                messages.put(char)
        except (EOFError, OSError):
            pass
    threading.Thread(target=reader, daemon=True).start()
    output, deadline = "", time.monotonic()+40
    try:
        found = None
        while time.monotonic() < deadline:
            try:
                output += messages.get(timeout=.2)
            except queue.Empty:
                if (not process.isalive()) if use_pty else (process.poll() is not None):
                    break
            clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
            clean = re.sub(r"\x1b\].*?(?:\x07|\x1b\\)", "", clean, flags=re.S)
            found = re.search(r"(http://127\.0\.0\.1:17864/oauth/authoring/authorize\?[^\s]+)\s", clean)
            if found:
                break
        assert found, "Client did not start OAuth authorization: " + re.sub(r"https?://\S+", "[url]", output)[-1500:]
        with httpx.Client(cookies={"rpg_session": session}) as browser:
            page = browser.get(found[1])
            assert page.status_code == 200
            rid = re.search("name='request_id' value='([^']+)'", page.text)[1]
            csrf = re.search("name='csrf' value='([^']+)'", page.text)[1]
            approved = browser.post(base+"/oauth/authoring/authorize", data=dict(request_id=rid, csrf=csrf, decision="allow"))
            callback = approved.headers["location"]
        if use_pty:
            process.write(callback+"\r")
            deadline = time.monotonic()+40
            while process.isalive() and time.monotonic() < deadline:
                time.sleep(.1)
            assert not process.isalive() and process.exitstatus == 0, "Client OAuth login failed"
        else:
            process.stdin.write(callback+"\n")
            process.stdin.flush()
            process.wait(timeout=40)
            assert process.returncode == 0, "Client OAuth login failed"
    finally:
        if use_pty:
            process.close(force=True)
        else:
            if process.poll() is None:
                process.kill()
            process.wait()


def rpc(process, method, params, request_id):
    process.stdin.write(json.dumps(dict(id=request_id, method=method, params=params))+"\n")
    process.stdin.flush()
    while line := process.stdout.readline():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if message.get("id") == request_id:
            assert "error" not in message, {"method": method, "error": message.get("error")}
            return message["result"]
    raise AssertionError("App server closed before RPC result")


def test_installed_codex_oauth_discovery_and_tool_call(live_server, creator, tmp_path):
    codex = shutil.which("codex.cmd") or shutil.which("codex")
    assert codex, "Codex must be installed for --clients"
    home = tmp_path / "codex"
    home.mkdir()
    (home / "config.toml").write_text('mcp_oauth_credentials_store = "file"\n[mcp_servers.authoring]\nurl = "'+live_server+'/mcp/authoring"\nscopes = '+json.dumps(oauth.SCOPES)+'\n', encoding="utf-8")
    env = dict(os.environ, CODEX_HOME=str(home))
    with connect() as db:
        session = auth._issue_session(db, creator["uid"])
    login_with_browser_session([codex, "mcp", "login", "authoring", "--no-browser", "--scopes", ",".join(oauth.SCOPES)], env, tmp_path, session, live_server)
    process = subprocess.Popen([codex, "app-server"], cwd=tmp_path, env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        rpc(process, "initialize", dict(clientInfo=dict(name="authoring-acceptance", version="1"), capabilities=dict(experimentalApi=True)), 1)
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()
        thread = rpc(process, "thread/start", dict(cwd=str(tmp_path), ephemeral=True), 2)
        tid = thread["thread"]["id"]
        status = rpc(process, "mcpServerStatus/list", dict(threadId=tid, serverName="authoring"), 3)
        assert "authoring_get_contract" in json.dumps(status)
        result = rpc(process, "mcpServer/tool/call", dict(threadId=tid, server="authoring", tool="authoring_get_contract", arguments={}), 4)
        assert not result.get("isError") and result["structuredContent"]["version"] == 1
    finally:
        process.kill()
        process.wait()


def test_installed_claude_oauth_and_discovery(live_server, creator, tmp_path):
    claude = shutil.which("claude.exe") or shutil.which("claude")
    assert claude, "Claude Code must be installed for --clients"
    home = tmp_path / "claude"
    home.mkdir()
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(home), DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1")
    configuration = dict(type="http", url=live_server+"/mcp/authoring", oauth=dict(scopes=" ".join(oauth.SCOPES)))
    added = subprocess.run([claude, "mcp", "add-json", "--scope", "user", "authoring", json.dumps(configuration)], env=env, cwd=tmp_path, capture_output=True, timeout=30)
    assert added.returncode == 0
    with connect() as db:
        session = auth._issue_session(db, creator["uid"])
    login_with_browser_session([claude, "mcp", "login", "authoring", "--no-browser"], env, tmp_path, session, live_server)
    status = subprocess.run([claude, "mcp", "get", "authoring"], env=env, cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert status.returncode == 0 and "Connected" in status.stdout
    env.update(ANTHROPIC_API_KEY="sk-ant-local-authoring-test", ANTHROPIC_BASE_URL=live_server,
               ENABLE_TOOL_SEARCH="false", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
    for key in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(key, None)
    CLAUDE_TOOL_RESULTS.clear()
    called = subprocess.run([claude, "-p", "Call authoring_get_contract with section summary once, then report success.",
                             "--max-turns", "3", "--output-format", "json", "--allowedTools", "mcp__authoring__authoring_get_contract"],
                            env=env, cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert called.returncode == 0, "Claude tool call failed: " + called.stderr[-500:]
    assert CLAUDE_TOOL_RESULTS and "workflow" in json.dumps(CLAUDE_TOOL_RESULTS), "Claude did not receive the real MCP result"
