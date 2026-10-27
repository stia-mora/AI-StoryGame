# ruff: noqa: F811 -- imported pytest fixtures are injected by name.
import asyncio
import base64
import hashlib
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg import DatabaseError
from psycopg.types.json import Jsonb

import app
from platform_app import auth, federation
from platform_app.authoring import oauth, preview, service
from platform_app.db import connect
from platform_app.player import catalog, wallet
from tests.integration.test_authoring import creator, imported, isolated_database  # noqa: F401


def configured(creator, files=None):
    project, _, _, revision = imported(creator, files)
    with connect() as db:
        profile = db.execute("insert into player_model_profiles(name,credential_owner_id,api_id,model,max_output) values('preview',%s,'test','text',1024) returning *", (creator["admin"]["id"],)).fetchone()
        db.execute("insert into app_config(key,value) values('authoring',%s) on conflict(key) do update set value=excluded.value", (Jsonb(dict(preview_profile_id=profile["id"])),))
    return project, revision, profile


def test_frozen_content_blocks_legacy_writers_but_allows_author_review(creator):
    _, _, _, revision = imported(creator)
    for statement in (
        "update scripts set title='modified' where id=%s",
        "update script_chapters set content='modified' where script_id=%s",
        "update script_overrides set data='{}' where script_id=%s",
        "delete from chapter_facts where script_id=%s",
    ):
        with pytest.raises(DatabaseError) as exc:
            with connect() as db:
                db.execute(statement, (revision["script_id"],))
        assert exc.value.sqlstate == "P7501"
    service.review(creator["uid"], revision["id"], "原创作品，作者本人授权平台游玩。")
    assert service.submit(creator["uid"], revision["id"])["status"] == "pending_review"


def test_cross_project_concurrent_upload_quota(creator):
    projects = [service.create_project(creator["uid"], uuid.uuid4().hex, "quota") for _ in range(8)]
    def attempt(project):
        try:
            service.begin_upload(creator["uid"], project["id"], 100, "a"*64)
            return True
        except HTTPException as exc:
            assert exc.status_code == 429
            return False
    with ThreadPoolExecutor(8) as pool:
        assert sum(pool.map(attempt, projects)) == 4


@pytest.mark.parametrize("reason", ["expired", "deactivated", "player", "provider_off", "scope"])
def test_authoring_authentication_rejects_invalid_access(creator, monkeypatch, reason):
    pat = federation.create_pat(creator["uid"], "limited", ["authoring:read"])
    with connect() as db:
        if reason == "expired":
            db.execute("update personal_access_tokens set expires_at=now()-interval '1 second' where id=%s", (pat["pat"]["id"],))
        if reason == "deactivated":
            db.execute("update users set deactivated_at=now() where id=%s", (creator["uid"],))
        if reason == "player":
            db.execute("update users set account_mode='player' where id=%s", (creator["uid"],))
    if reason == "provider_off":
        monkeypatch.setattr(federation, "provider_enabled", lambda: False)
    with pytest.raises(HTTPException):
        oauth.verify_bearer(pat["token"], "authoring:write" if reason == "scope" else "authoring:read")


def test_oauth_never_uses_local_login_fallback_and_account_revocation_covers_grants(creator, monkeypatch):
    from starlette.requests import Request
    monkeypatch.setenv("RPG_REQUIRE_AUTH", "0")
    with pytest.raises(HTTPException) as exc:
        oauth.session_user(Request({"type": "http", "headers": []}))
    assert exc.value.status_code == 401
    access = "test-access-"+uuid.uuid4().hex
    with connect() as db:
        db.execute("insert into authoring_oauth_clients(id,name,redirect_uris) values('revocation-client','test','[]') on conflict do nothing")
        db.execute("insert into authoring_oauth_grants(id,user_id,client_id,scopes,redirect_uri,challenge,resource,access_hash,access_expires) "
                   "values(%s,%s,'revocation-client',%s,'http://127.0.0.1/callback','test',%s,%s,now()+interval '1 hour')",
                   (uuid.uuid4(), creator["uid"], Jsonb(oauth.SCOPES), oauth.resource(), oauth.digest(access)))
    assert oauth.verify_bearer(access)["user"]["id"] == creator["uid"]
    with connect() as db:
        federation.revoke_account_tokens(db, creator["uid"])
    with pytest.raises(HTTPException):
        oauth.verify_bearer(access)


def test_preview_creation_key_binds_identity_and_location(creator):
    _, revision, _ = configured(creator)
    key = str(uuid.uuid4())
    created = preview.create(creator["uid"], revision["id"], "keeper", key)
    with pytest.raises(HTTPException) as exc:
        preview.create(creator["uid"], revision["id"], "visitor", key)
    assert exc.value.status_code == 409
    save = catalog.player_save(creator["uid"], created["save_id"])
    assert save["state_snapshot"]["world"]["current_location"] == "渡口"
    assert save["state_snapshot"]["player"]["name"] == "林舟"
    assert save["state_snapshot"]["player"]["guide"]["subject"] == "keeper"
    assert save["state_snapshot"]["player"]["bound_npc_card_id"]
    assert save["state_snapshot"]["player"]["speech_style"]
    from platform_app.knowledge.session import ensure_game_session
    assert ensure_game_session(creator["uid"], created["save_id"], save["state_snapshot"])["script_id"] == revision["script_id"]


def test_restart_cleans_running_preview_without_billing_request(creator):
    project = service.create_project(creator["uid"], uuid.uuid4().hex, "restart")
    jid = uuid.uuid4()
    with connect() as db:
        db.execute("insert into authoring_jobs(id,project_id,owner_id,kind,status,input,created_at) values(%s,%s,%s,'preview','running','{}',now()-interval '10 minutes')", (jid, project["id"], creator["uid"]))
    preview.reconcile()
    assert service.get_job(creator["uid"], str(jid))["status"] == "failed"


def test_approval_publish_new_version_preserves_old_snapshot_and_can_suspend(creator):
    from platform_app.authoring.examples import example_files
    project, revision, profile = configured(creator)
    old_preview = preview.create(creator["uid"], revision["id"], "keeper", str(uuid.uuid4()))
    with connect() as db:
        cookie = auth._issue_session(db, creator["admin"]["id"])
    client = TestClient(app.app)
    client.cookies.set("rpg_session", cookie)
    service.review(creator["uid"], revision["id"], "原创授权")
    first = service.submit(creator["uid"], revision["id"])
    response = client.post("/api/authoring/admin", json=dict(action="approve", submission_id=str(first["id"]), profile_id=profile["id"]))
    assert response.status_code == 200, response.text
    before = next(s for s in catalog.listed_stories() if s["authoring_project_id"] == project["id"])
    assert catalog.public_story(before)["author"] == "Creator"
    project = service.get_draft(creator["uid"], project["id"])["project"]
    _, _, _, second_revision = imported(creator, example_files(True), project)
    service.review(creator["uid"], second_revision["id"], "原创授权第二版")
    second = service.submit(creator["uid"], second_revision["id"])
    response = client.post("/api/authoring/admin", json=dict(action="approve", submission_id=str(second["id"]), profile_id=profile["id"]))
    assert response.status_code == 200, response.text
    after = next(s for s in catalog.listed_stories() if s["authoring_project_id"] == project["id"])
    assert before["id"] == after["id"]
    old = catalog.player_save(creator["uid"], old_preview["save_id"])
    assert catalog.for_save(old)["script_id"] == revision["script_id"]
    assert catalog.story(after["id"])["script_id"] == second_revision["script_id"]
    assert client.get(f"/api/authoring/admin/submissions/{second['id']}").json()["chapters"]
    response = client.post("/api/authoring/admin", json=dict(action="suspend", submission_id=str(second["id"]), reason="review"))
    assert response.status_code == 200, response.text
    assert not any(s["id"] == after["id"] for s in catalog.listed_stories())
    with pytest.raises(HTTPException):
        catalog.for_save(old)


def test_new_previews_can_use_reconfigured_model_without_changing_old_snapshot(creator):
    _, revision, profile = configured(creator)
    old = preview.create(creator["uid"], revision["id"], "keeper", str(uuid.uuid4()))
    with connect() as db:
        other = db.execute("insert into player_model_profiles(name,credential_owner_id,api_id,model,max_output) values('replacement',%s,'test','text',1024) returning id", (creator["admin"]["id"],)).fetchone()
        db.execute("update player_model_profiles set enabled=false where id=%s", (profile["id"],))
        db.execute("update app_config set value=%s where key='authoring'", (Jsonb(dict(preview_profile_id=other["id"])),))
    new = preview.create(creator["uid"], revision["id"], "keeper", str(uuid.uuid4()))
    assert catalog.for_save(catalog.player_save(creator["uid"], new["save_id"]))["profile_id"] == other["id"]
    assert catalog.player_save(creator["uid"], old["save_id"])["player_story_snapshot"]["profile_id"] == profile["id"]


def test_private_cover_remains_bound_to_owned_save(creator):
    from platform_app.authoring.examples import example_files
    files = example_files()
    cover = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    files["cover.png"] = cover
    files["authoring.json"]["media"] = [dict(path="cover.png", sha256=hashlib.sha256(cover).hexdigest(), purpose="cover")]
    _, revision, _ = configured(creator, files)
    created = preview.create(creator["uid"], revision["id"], "keeper", str(uuid.uuid4()))
    url = catalog.view(creator["uid"], created["save_id"])["story"]["cover"]
    assert url == f"/api/player/saves/{created['save_id']}/cover"
    with connect() as db:
        cookie = auth._issue_session(db, creator["uid"])
        db.execute("update player_stories set cover='/api/storage/unrelated.png' where script_id=%s", (revision["script_id"],))
    client = TestClient(app.app)
    client.cookies.set("rpg_session", cookie)
    response = client.get(url)
    assert response.status_code == 200 and response.content == cover
    assert response.headers["cache-control"].startswith("private")
    with connect() as db:
        other_cookie = auth._issue_session(db, creator["admin"]["id"])
    client.cookies.set("rpg_session", other_cookie)
    assert client.get(url).status_code == 404


def test_preview_generation_settles_once_and_never_uses_normal_balance(creator, monkeypatch):
    from starlette.responses import StreamingResponse

    from platform_app import branches
    from platform_app.api.player import event
    from platform_app.player.meter import current
    _, revision, _ = configured(creator)
    created = preview.create(creator["uid"], revision["id"], "keeper", str(uuid.uuid4()))
    quote = preview.quote(creator["uid"], revision["id"], created["save_id"], "opening")
    monkeypatch.setattr("platform_app.branches.runtime.schedule_llm_summary", lambda *a: None)
    async def opening(api_user):
        async def chunks():
            run = current(api_user["id"])
            run.record(str(uuid.uuid4()), "openai", "test", {"prompt_tokens": 100, "completion_tokens": 50})
            yield event("token", {"text": "林舟提起灯，沿渡口走向钟声。"})
            save = catalog.player_save(api_user["id"], created["save_id"])
            run.committing = True
            branches.record_runtime_turn("", "林舟提起灯，沿渡口走向钟声。", user_id=api_user["id"], state_data=save["state_snapshot"])
        return StreamingResponse(chunks())
    monkeypatch.setattr("routes.game.opening.api_opening", opening)
    initial = wallet.preview_wallet(creator["uid"])
    async def scenario():
        args = dict(revision_id=revision["id"], save_id=created["save_id"], kind="opening", message="",
                    quote_id=quote["id"], request_id=str(uuid.uuid4()), cap_micro=quote["cap_micro"])
        result = await preview.execute(creator["uid"], **args)
        assert (await preview.execute(creator["uid"], **args))["reused"]
        await asyncio.gather(*list(preview.TASKS))
        return service.get_job(creator["uid"], result["job_id"])
    job = asyncio.run(scenario())
    assert job["status"] == "succeeded", job
    final = wallet.preview_wallet(creator["uid"])
    assert initial["preview_micro"]-final["preview_micro"] == 300000
    assert final["preview_held_micro"] == 0 and initial["free_micro"] == final["free_micro"]
    assert catalog.view(creator["uid"], created["save_id"])["has_opening"]


def test_preview_insufficient_funds_and_failed_generation_refund(creator, monkeypatch):
    from platform_app.player import catalog
    _, revision, _ = configured(creator)
    created = preview.create(creator["uid"], revision["id"], "visitor", str(uuid.uuid4()))
    quote = preview.quote(creator["uid"], revision["id"], created["save_id"], "opening")
    save = catalog.player_save(creator["uid"], created["save_id"])
    with connect() as db:
        db.execute("update player_wallets set preview_micro=0,permanent_micro=100000000000 where user_id=%s", (creator["uid"],))
    with pytest.raises(HTTPException) as exc:
        wallet.reserve(creator["uid"], save, quote["id"], str(uuid.uuid4()), "opening", "opening", "")
    assert exc.value.status_code == 402
    with connect() as db:
        db.execute("update player_wallets set preview_micro=10000000000 where user_id=%s", (creator["uid"],))
    initial = wallet.preview_wallet(creator["uid"])
    async def fail(*args, **kwargs):
        raise RuntimeError("provider failure")
    monkeypatch.setattr("routes.game.opening.api_opening", fail)
    async def scenario():
        job = await preview.execute(creator["uid"], revision["id"], created["save_id"], "opening", "", quote["id"], str(uuid.uuid4()), quote["cap_micro"])
        await asyncio.gather(*list(preview.TASKS))
        return service.get_job(creator["uid"], job["job_id"])
    assert asyncio.run(scenario())["status"] == "failed"
    final = wallet.preview_wallet(creator["uid"])
    assert final["preview_micro"] == initial["preview_micro"] and final["preview_held_micro"] == 0
    assert final["permanent_micro"] == initial["permanent_micro"]


def test_failed_import_rolls_back_content_and_recovery_is_idempotent(creator, monkeypatch):
    from platform_app.knowledge import script_pack
    from tests.integration.test_authoring import upload
    project, upload_id = upload(creator)
    with connect() as db:
        before = db.execute("select count(*) as n from scripts where owner_id=%s", (creator["uid"],)).fetchone()["n"]
    original = script_pack.import_script_pack
    def fail_after_import(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("interrupted before commit")
    monkeypatch.setattr(script_pack, "import_script_pack", fail_after_import)
    job = service.import_draft(creator["uid"], project["id"], upload_id, 0)
    for _ in range(100):
        if service.get_job(creator["uid"], job["job_id"])["status"] == "failed":
            break
        time.sleep(.05)
    with connect() as db:
        assert db.execute("select count(*) as n from scripts where owner_id=%s", (creator["uid"],)).fetchone()["n"] == before
        db.execute("update authoring_jobs set status='running' where id=%s", (job["job_id"],))
    monkeypatch.setattr(script_pack, "import_script_pack", original)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(service.run_import, [job["job_id"]]*2))
    assert service.get_job(creator["uid"], job["job_id"])["status"] == "succeeded"
    assert len(service.get_draft(creator["uid"], project["id"])["revisions"]) == 1


def test_chunk_bounds_retries_and_expiry(creator):
    from platform_app.authoring.contract import CHUNK_BYTES
    project = service.create_project(creator["uid"], uuid.uuid4().hex, "upload")
    raw = b"first"
    uid = service.begin_upload(creator["uid"], project["id"], len(raw), hashlib.sha256(raw).hexdigest())["upload_id"]
    with pytest.raises(HTTPException):
        service.upload_chunk(creator["uid"], uid, 0, base64.b64encode(b"x"*(CHUNK_BYTES+1)).decode())
    service.upload_chunk(creator["uid"], uid, 1, base64.b64encode(raw).decode())
    with pytest.raises(HTTPException) as exc:
        service.complete_upload(creator["uid"], uid)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException):
        service.upload_chunk(creator["uid"], uid, 1, base64.b64encode(b"other").decode())
    with connect() as db:
        db.execute("update authoring_uploads set created_at=now()-interval '25 hours' where id=%s", (uid,))
    preview.reconcile()
    with pytest.raises(HTTPException):
        service.complete_upload(creator["uid"], uid)


@pytest.mark.skipif(not os.getenv("AUTHORING_PRIVATE_PACK"), reason="Private local pack is opt-in")
def test_private_v2_pack_compatibility(creator):
    from pathlib import Path

    from platform_app.knowledge.script_pack import import_script_pack
    raw = Path(os.environ["AUTHORING_PRIVATE_PACK"]).read_bytes()
    with connect() as db:
        result = import_script_pack(raw, creator["uid"], db=db)
        assert not result["warnings"]
        assert db.execute("select count(*) as n from script_chapters where script_id=%s", (result["script_id"],)).fetchone()["n"] > 0
        assert not db.execute("select is_public from scripts where id=%s", (result["script_id"],)).fetchone()["is_public"]


@pytest.mark.skipif(not os.getenv("AUTHORING_SOURCE_DATABASE_URL"), reason="Paid provider check is opt-in with --live-model")
def test_real_configured_provider_saves_opening_turn_and_guide(creator, monkeypatch):
    import psycopg
    from psycopg.rows import dict_row

    from utils.crypto import decrypt_api_key, encrypt_api_key
    with psycopg.connect(os.environ["AUTHORING_SOURCE_DATABASE_URL"], row_factory=dict_row) as source:
        configured_profile = source.execute("select * from player_model_profiles where enabled order by id limit 1").fetchone()
        assert configured_profile, "No configured platform model"
        cred = source.execute("select * from user_api_credentials where user_id=%s and api_id=%s and enabled",
                              (configured_profile["credential_owner_id"], configured_profile["api_id"])).fetchone()
    assert cred and os.environ["AUTHORING_SOURCE_MASTER_KEY"], "No available test credential"
    from urllib.parse import urlsplit
    host = urlsplit(cred["base_url_override"]).hostname
    if host:
        # A local Windows system proxy may not support urllib's CONNECT transport.
        for variable in ("NO_PROXY", "no_proxy"):
            monkeypatch.setenv(variable, os.getenv(variable, "") + "," + host)
    with monkeypatch.context() as context:
        context.setenv("RPG_MASTER_KEY", os.environ["AUTHORING_SOURCE_MASTER_KEY"])
        key = decrypt_api_key(cred["encrypted_key"], cred["user_id"], cred["api_id"])
    assert key, "Configured credential could not be decrypted"
    _, revision, profile = configured(creator)
    with connect() as db:
        db.execute("update player_model_profiles set api_id=%s,model=%s,max_output=1536 where id=%s",
                   (configured_profile["api_id"], configured_profile["model"], profile["id"]))
        db.execute("insert into user_api_credentials(user_id,api_id,encrypted_key,base_url_override,metadata,auth_mode) values(%s,%s,%s,%s,%s,%s)",
                   (creator["admin"]["id"], cred["api_id"], encrypt_api_key(key, creator["admin"]["id"], cred["api_id"]),
                    cred["base_url_override"], Jsonb(cred["metadata"]), cred["auth_mode"]))
    del key
    created = preview.create(creator["uid"], revision["id"], "keeper", str(uuid.uuid4()))
    initial = wallet.preview_wallet(creator["uid"])
    async def scenario():
        for kind, message in (("opening", ""), ("turn", "我提起灯，查看钟声传来的方向。"), ("guide", "我现在在哪里，有什么已经确认的情况？")):
            quote = preview.quote(creator["uid"], revision["id"], created["save_id"], kind, message)
            assert quote["cap_micro"] <= 500*wallet.MICRO
            result = await preview.execute(creator["uid"], revision["id"], created["save_id"], kind, message,
                                           quote["id"], str(uuid.uuid4()), quote["cap_micro"])
            await asyncio.wait_for(asyncio.gather(*list(preview.TASKS)), timeout=180)
            job = service.get_job(creator["uid"], result["job_id"])
            assert job["status"] == "succeeded", {"kind": kind, "status": job["status"], "error": job["error"]}
            print(f"Live provider: {kind} saved; preview funding settled", flush=True)
    asyncio.run(scenario())
    assert catalog.view(creator["uid"], created["save_id"])["has_opening"]
    final = wallet.preview_wallet(creator["uid"])
    assert final["preview_held_micro"] == 0 and final["preview_micro"] < initial["preview_micro"]
    assert final["free_micro"] == initial["free_micro"] and final["permanent_micro"] == initial["permanent_micro"]
