"""Real network clients, including both negotiated MCP protocol eras."""
# ruff: noqa: F811 -- imported pytest fixtures are injected by name.
import asyncio
import base64
import hashlib
import json
import random
import re
import socket
import threading
import time
import uuid
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from mcp import Client
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientMetadata

from platform_app import auth, federation
from platform_app.authoring import oauth
from platform_app.authoring.examples import example_files, package_bytes
from platform_app.db import connect
from tests.integration.test_authoring import creator, isolated_database  # noqa: F401

CLAUDE_TOOL_RESULTS = []


async def client_test_model(request):
    """A deterministic inference stand-in tests the real Claude MCP machinery without paid calls."""
    data = await request.json()
    results = [block for message in data.get("messages", []) for block in
               (message.get("content", []) if isinstance(message.get("content"), list) else [])
               if block.get("type") == "tool_result" and block.get("tool_use_id") == "authoring-contract"]
    if results:
        CLAUDE_TOOL_RESULTS.extend(results)
        content = dict(type="text", text="Authoring contract received successfully.")
        stop = "end_turn"
    else:
        tool = next((t["name"] for t in data.get("tools", []) if t.get("name", "").endswith("authoring_get_contract")), None)
        content = dict(type="tool_use", id="authoring-contract", name=tool, input={"section": "summary"}) if tool else dict(type="text", text="Ready")
        stop = "tool_use" if tool else "end_turn"
    message = dict(id="msg_authoring", type="message", role="assistant", model=data.get("model", "test"),
                   content=[content], stop_reason=stop, stop_sequence=None, usage=dict(input_tokens=10, output_tokens=10))
    if not data.get("stream"):
        return JSONResponse(message)
    async def events():
        def event(kind, value):
            return f"event: {kind}\ndata: {json.dumps(value)}\n\n"
        yield event("message_start", dict(type="message_start", message={**message, "content": [], "stop_reason": None}))
        start = {**content, "input": {}} if content["type"] == "tool_use" else dict(type="text", text="")
        yield event("content_block_start", dict(type="content_block_start", index=0, content_block=start))
        delta = dict(type="input_json_delta", partial_json=json.dumps(content["input"])) if content["type"] == "tool_use" else dict(type="text_delta", text=content["text"])
        yield event("content_block_delta", dict(type="content_block_delta", index=0, delta=delta))
        yield event("content_block_stop", dict(type="content_block_stop", index=0))
        yield event("message_delta", dict(type="message_delta", delta=dict(stop_reason=stop, stop_sequence=None), usage=dict(output_tokens=10)))
        yield event("message_stop", dict(type="message_stop"))
    return StreamingResponse(events(), media_type="text/event-stream")


def start_server():
    from app import app as platform
    @asynccontextmanager
    async def lifespan(_):
        async with platform.router.lifespan_context(platform):
            yield
    application = FastAPI(lifespan=lifespan)
    from fastapi import Request
    @application.post("/v1/messages")
    async def messages(request: Request):
        return await client_test_model(request)
    @application.post("/v1/messages/count_tokens")
    def count_tokens():
        return dict(input_tokens=10)
    application.mount("/", platform)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 17864))
    server = uvicorn.Server(uvicorn.Config(application, log_level="warning", timeout_graceful_shutdown=3))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(400):
        if server.started:
            break
        time.sleep(.05)
    assert server.started
    yield "http://127.0.0.1:17864"
    server.should_exit = True
    thread.join(10)
    sock.close()
    assert not thread.is_alive(), "Full application lifespan did not stop"


def test_http_upload_streams_chunked_and_enforces_actual_size(live_server, creator, monkeypatch):
    from platform_app.authoring import service

    uid = creator["uid"]
    token = federation.create_pat(uid, "stream", oauth.SCOPES)["token"]
    project = service.create_project(uid, uuid.uuid4().hex, "流式上传")
    raw = b"streamed-data" * 25000
    upload = service.begin_upload(uid, project["id"], len(raw), hashlib.sha256(raw).hexdigest())
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"}
    def chunks(data):
        for start in range(0, len(data), 17000):
            yield data[start:start + 17000]
    with httpx.Client(timeout=30) as client:
        response = client.put(live_server + upload["http_url"], headers=headers, content=chunks(raw))
        assert response.status_code == 200, response.text
        assert service.package(uid, upload["upload_id"])[1] == raw
        monkeypatch.setenv("RPG_UPLOAD_BODY_LIMIT_BYTES", "128")
        other = service.begin_upload(uid, project["id"], 200, hashlib.sha256(b"x" * 200).hexdigest())
        denied = client.put(live_server + other["http_url"], headers=headers, content=chunks(b"x" * 200))
        assert denied.status_code == 413, denied.text


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_real_sdk_upload_import_retry_and_scope(live_server, creator, mode, monkeypatch):
    pat = federation.create_pat(creator["uid"], "SDK", oauth.SCOPES)["token"]
    from psycopg.types.json import Jsonb

    from platform_app import branches
    from platform_app.api.player import event
    from platform_app.player import catalog
    from platform_app.player.meter import current
    with connect() as db:
        profile = db.execute("insert into player_model_profiles(name,credential_owner_id,api_id,model,max_output) values('SDK preview',%s,'test','text',1024) returning id", (creator["admin"]["id"],)).fetchone()
        db.execute("insert into app_config(key,value) values('authoring',%s) on conflict(key) do update set value=excluded.value", (Jsonb(dict(preview_profile_id=profile["id"])),))
    monkeypatch.setattr("platform_app.branches.runtime.schedule_llm_summary", lambda *a: None)
    async def opening(api_user):
        async def chunks():
            run = current(api_user["id"])
            run.record(str(uuid.uuid4()), "openai", "test", {"prompt_tokens": 10, "completion_tokens": 10})
            text = "林舟提起灯，沿渡口走向钟声。"
            yield event("token", dict(text=text))
            save = catalog.player_save(api_user["id"], run.save_id)
            run.committing = True
            branches.record_runtime_turn("", text, user_id=api_user["id"], state_data=save["state_snapshot"])
        return StreamingResponse(chunks())
    monkeypatch.setattr("routes.game.opening.api_opening", opening)
    async def scenario():
        async with httpx.AsyncClient(headers={"Authorization": "Bearer "+pat}) as http:
            async with Client(streamable_http_client(live_server+"/mcp/authoring", http_client=http), mode=mode) as client:
                tools = await client.list_tools()
                assert len(tools.tools) == 11
                async def call(name, data):
                    result = await client.call_tool("authoring_"+name, data)
                    assert not result.is_error, result
                    return result.structured_content
                contract = await call("get_contract", {})
                assert contract["version"] == 1
                project = await call("create_project", dict(project_key=uuid.uuid4().hex, title="SDK作品"))
                files = example_files()
                # Deterministic original test data ensures the ZIP needs multiple MCP chunks.
                text = files["chapters.jsonl"][0]["content"] + "\n" + base64.b64encode(random.Random(7).randbytes(210000)).decode()
                digest = hashlib.sha256(text.encode()).hexdigest()
                files["chapters.jsonl"][0]["content"] = text
                source = files["authoring.json"]["sources"][0]
                source["sha256"] = digest
                source["chapters"][0].update(sha256=digest, line_count=2)
                files["overrides.json"]["guide_world"]["facts"][0]["evidence"][0]["chapter_sha256"] = digest
                raw = package_bytes(files)
                upload = await call("begin_upload", dict(project_id=project["id"], size=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
                assert len(raw) > upload["chunk_bytes"]
                for part, start in enumerate(range(0, len(raw), upload["chunk_bytes"])):
                    chunk = dict(upload_id=upload["upload_id"], part=part, data=base64.b64encode(raw[start:start+upload["chunk_bytes"]]).decode())
                    await call("upload_chunk", chunk)
                    await call("upload_chunk", chunk)
                await call("complete_upload", dict(upload_id=upload["upload_id"]))
                assert (await call("validate_package", dict(upload_id=upload["upload_id"])))["valid"]
                job = await call("import_draft", dict(project_id=project["id"], upload_id=upload["upload_id"], expected_version=0))
                for _ in range(100):
                    status = await call("get_job", dict(job_id=job["job_id"]))
                    if status["status"] in ("succeeded", "failed"):
                        break
                    await asyncio.sleep(.05)
                assert status["status"] == "succeeded", status
                assert (await call("import_draft", dict(project_id=project["id"], upload_id=upload["upload_id"], expected_version=0)))["job_id"] == job["job_id"]
                draft = await call("get_draft", dict(project_id=project["id"]))
                denied = await client.call_tool("authoring_submit", dict(revision_id=draft["revisions"][0]["id"]))
                assert denied.is_error and denied.structured_content["code"] == "E_409"
                rid = draft["revisions"][0]["id"]
                created = await call("preview", dict(mode="create", data=dict(revision_id=rid, identity_id="keeper", request_id=str(uuid.uuid4()))))
                quoted = await call("preview", dict(mode="quote", data=dict(revision_id=rid, save_id=created["save_id"], kind="opening")))
                executed = await call("preview", dict(mode="execute", data=dict(revision_id=rid, save_id=created["save_id"], kind="opening", message="", quote_id=quoted["id"], cap_micro=quoted["cap_micro"], request_id=str(uuid.uuid4()))))
                for _ in range(100):
                    status = await call("get_job", dict(job_id=executed["job_id"]))
                    if status["status"] in ("succeeded", "failed"):
                        break
                    await asyncio.sleep(.05)
                assert status["status"] == "succeeded", status
                with connect() as db:
                    cookie = auth._issue_session(db, creator["uid"])
                async with httpx.AsyncClient(cookies={"rpg_session": cookie}) as browser:
                    reviewed = await browser.post(live_server+"/api/authoring/action/review", json=dict(revision_id=rid, rights_note="原创作品，作者本人确认授权。"))
                    assert reviewed.status_code == 200
                submitted = await call("submit", dict(revision_id=rid))
                assert submitted["status"] == "pending_review"
    asyncio.run(scenario())


class Storage:
    tokens = None
    client = None
    async def get_tokens(self): return self.tokens
    async def set_tokens(self, value): self.tokens = value
    async def get_client_info(self): return self.client
    async def set_client_info(self, value): self.client = value


def test_sdk_real_oauth_discovery_and_consent(live_server, creator):
    with connect() as db:
        session = auth._issue_session(db, creator["uid"])
    async def scenario():
        received = {}
        async def redirect(url):
            async with httpx.AsyncClient(cookies={"rpg_session": session}) as browser:
                page = await browser.get(url)
                assert page.status_code == 200, page.text
                rid = re.search("name='request_id' value='([^']+)'", page.text)[1]
                csrf = re.search("name='csrf' value='([^']+)'", page.text)[1]
                response = await browser.post(live_server+"/oauth/authoring/authorize", data=dict(request_id=rid, csrf=csrf, decision="allow"))
                received.update(parse_qs(urlsplit(response.headers["location"]).query))
        async def callback():
            return AuthorizationCodeResult(code=received["code"][0], state=received["state"][0], iss=received["iss"][0])
        provider = OAuthClientProvider(live_server+"/mcp/authoring", OAuthClientMetadata(
            client_name="Official SDK OAuth", redirect_uris=["http://127.0.0.1:17865/callback"],
            grant_types=["authorization_code", "refresh_token"], response_types=["code"],
            token_endpoint_auth_method="none", scope=" ".join(oauth.SCOPES)), Storage(), redirect, callback)
        async with httpx.AsyncClient(auth=provider) as http:
            async with Client(streamable_http_client(live_server+"/mcp/authoring", http_client=http)) as client:
                response = await client.call_tool("authoring_get_contract", {})
                assert not response.is_error and response.structured_content["version"] == 1
    asyncio.run(scenario())
