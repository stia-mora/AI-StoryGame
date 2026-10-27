"""Real isolated Postgres and real HTTP MCP client tests, no paid provider calls."""
import base64
import hashlib
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

import app
from platform_app import auth, federation
from platform_app.authoring import oauth, service
from platform_app.authoring.examples import example_files, package_bytes
from platform_app.db import connect, init_db
from platform_app.player import wallet


@pytest.fixture(scope="session", autouse=True)
def isolated_database():
    from psycopg.conninfo import conninfo_to_dict
    assert conninfo_to_dict(os.environ["DATABASE_URL"])["dbname"].startswith("authoring_test_"), "Use scripts/check_authoring.py"
    init_db()


@pytest.fixture
def creator():
    with connect() as db:
        user = db.execute("insert into users(username,password_hash,display_name,account_mode,email_verified) values(%s,'test','Creator','creator',true) returning *",
                          ("authoring_"+uuid.uuid4().hex,)).fetchone()
        admin = db.execute("insert into users(username,password_hash,display_name,account_mode,role,email_verified) values(%s,'test','Admin','creator','admin',true) returning *",
                          ("admin_"+uuid.uuid4().hex,)).fetchone()
    return dict(user=user, admin=admin, uid=user["id"])


def upload(creator, files=None, project=None):
    project = project or service.create_project(creator["uid"], uuid.uuid4().hex, "原创项目")
    data = package_bytes(files)
    reference = service.begin_upload(creator["uid"], project["id"], len(data), hashlib.sha256(data).hexdigest())
    encoded = base64.b64encode(data).decode()
    service.upload_chunk(creator["uid"], reference["upload_id"], 0, encoded)
    service.upload_chunk(creator["uid"], reference["upload_id"], 0, encoded)
    service.complete_upload(creator["uid"], reference["upload_id"])
    return project, reference["upload_id"]


def imported(creator, files=None, project=None):
    project, upload_id = upload(creator, files, project)
    result = service.import_draft(creator["uid"], project["id"], upload_id, project["version"])
    for _ in range(100):
        job = service.get_job(creator["uid"], result["job_id"])
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(.05)
    assert job["status"] == "succeeded", job
    return project, upload_id, result, service.get_draft(creator["uid"], project["id"])["revisions"][0]


def test_import_retry_ownership_and_revision_conflict(creator):
    project, upload_id, result, revision = imported(creator)
    assert service.import_draft(creator["uid"], project["id"], upload_id, 0)["job_id"] == result["job_id"]
    with pytest.raises(HTTPException) as denied:
        service.get_draft(creator["admin"]["id"], project["id"])
    assert denied.value.status_code == 404
    files = example_files(True)
    _, other = upload(creator, files, project)
    with pytest.raises(HTTPException) as conflict:
        service.import_draft(creator["uid"], project["id"], other, 0)
    assert conflict.value.status_code == 409
    with connect() as db:
        script = db.execute("select * from scripts where id=%s", (revision["script_id"],)).fetchone()
    assert not script["is_public"] and script["authoring_locked"]


def test_creator_allowance_is_once_and_not_ordinary_credit(creator):
    uid = creator["uid"]
    with ThreadPoolExecutor(4) as executor:
        balances = list(executor.map(wallet.preview_wallet, [uid]*4))
    assert all(b["preview_micro"] == 10000*wallet.MICRO for b in balances)
    with connect() as db:
        assert db.execute("select count(*) n from player_ledger where user_id=%s and kind='creator_grant'", (uid,)).fetchone()["n"] == 1
        assert db.execute("select permanent_micro from player_wallets where user_id=%s", (uid,)).fetchone()["permanent_micro"] == 0
        db.execute("update users set account_mode='player' where id=%s", (uid,))
    with pytest.raises(HTTPException):
        wallet.preview_wallet(uid)


def test_preview_coupon_separate_and_player_denied(creator):
    uid = creator["uid"]
    with connect() as db:
        db.execute("insert into player_codes(code_hash,label,amount_micro,max_uses,purpose) values(%s,'preview',%s,2,'preview')",
                   (hashlib.sha256(b"PREVIEW").hexdigest(), 500*wallet.MICRO))
    result = wallet.redeem(uid, "PREVIEW")
    assert result["preview_micro"] == 10500*wallet.MICRO and result["permanent_micro"] == 0
    with pytest.raises(HTTPException):
        wallet.redeem(uid, "PREVIEW")
    with connect() as db:
        db.execute("update users set account_mode='player' where id=%s", (creator["admin"]["id"],))


def test_oauth_pkce_rotation_revoke_and_pat(creator):
    client = TestClient(app.app)
    original = auth.user_from_token
    auth.user_from_token = lambda token: creator["user"] if token == "test-session" else None
    client.cookies.set("rpg_session", "test-session")
    try:
        base = oauth.resource()
        assert client.get("/.well-known/oauth-protected-resource").json()["resource"] == base
        registration = client.post("/oauth/authoring/register", json=dict(redirect_uris=["http://127.0.0.1:23456/callback"], client_name="Test Agent")).json()
        verifier = "v"*64
        params = dict(client_id=registration["client_id"], redirect_uri="http://127.0.0.1:23456/callback", response_type="code",
                      scope=" ".join(oauth.SCOPES), resource=base, state="test", code_challenge_method="S256",
                      code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("="))
        response = client.get("/oauth/authoring/authorize", params=params)
        assert response.status_code == 200, response.text
        rid = re.search("name='request_id' value='([^']+)'", response.text)[1]
        csrf = re.search("name='csrf' value='([^']+)'", response.text)[1]
        consent = client.post("/oauth/authoring/authorize", data=dict(request_id=rid, csrf=csrf, decision="allow"), follow_redirects=False)
        code = parse_qs(urlsplit(consent.headers["location"]).query)["code"][0]
        exchange = dict(grant_type="authorization_code", code=code, code_verifier=verifier,
                        client_id=params["client_id"], redirect_uri=params["redirect_uri"], resource=base)
        tokens = client.post("/oauth/authoring/token", data=exchange)
        assert tokens.status_code == 200, tokens.text
        tokens = tokens.json()
        assert client.post("/oauth/authoring/token", data=exchange).status_code == 400
        assert oauth.verify_bearer(tokens["access_token"])["user"]["id"] == creator["uid"]
        refreshed = client.post("/oauth/authoring/token", data=dict(grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=params["client_id"], resource=base))
        assert refreshed.status_code == 200, refreshed.text
        client.post("/oauth/authoring/revoke", data=dict(client_id=params["client_id"], token=refreshed.json()["access_token"]))
        with pytest.raises(HTTPException):
            oauth.verify_bearer(refreshed.json()["access_token"])
        pat = federation.create_pat(creator["uid"], "agent", oauth.SCOPES)
        assert oauth.verify_bearer(pat["token"], "authoring:write")["user"]["id"] == creator["uid"]
        federation.revoke_pat(creator["uid"], pat["pat"]["id"])
        with pytest.raises(HTTPException):
            oauth.verify_bearer(pat["token"])
    finally:
        auth.user_from_token = original


def test_preview_create_quote_reserve_release(creator):
    from platform_app.authoring import preview
    project, _, _, revision = imported(creator)
    with connect() as db:
        profile = db.execute("insert into player_model_profiles(name,credential_owner_id,api_id,model,max_output) values('test',%s,'test','text',1024) returning *", (creator["admin"]["id"],)).fetchone()
        db.execute("insert into app_config(key,value) values('authoring',%s) on conflict(key) do update set value=excluded.value", (Jsonb(dict(preview_profile_id=profile["id"])),))
    key = str(uuid.uuid4())
    created = preview.create(creator["uid"], revision["id"], "keeper", key)
    assert preview.create(creator["uid"], revision["id"], "keeper", key)["save_id"] == created["save_id"]
    quote = preview.quote(creator["uid"], revision["id"], created["save_id"], "opening")
    assert quote["funding"] == "preview" and quote["affordable"]
    from platform_app.player import catalog
    save = catalog.player_save(creator["uid"], created["save_id"])
    request = str(uuid.uuid4())
    balance = wallet.preview_wallet(creator["uid"])
    req, replay = wallet.reserve(creator["uid"], save, quote["id"], request, "opening", "opening", "")
    assert not replay and req["funding"] == "preview"
    wallet.release(creator["uid"], request)
    assert wallet.preview_wallet(creator["uid"])["preview_micro"] == balance["preview_micro"]
