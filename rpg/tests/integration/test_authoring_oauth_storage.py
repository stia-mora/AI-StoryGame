"""Exercise bounded OAuth admission and cleanup against disposable Postgres."""
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

import app
from platform_app import auth
from platform_app.authoring import oauth
from platform_app.db import connect
from tests.integration.test_authoring import creator, isolated_database  # noqa: F401

pytestmark = pytest.mark.usefixtures("isolated_database")


def register(client):
    return client.post("/oauth/authoring/register", json={"redirect_uris": ["http://127.0.0.1:23456/callback"]})


def test_client_capacity_is_atomic_and_keeps_registered_clients(monkeypatch):
    monkeypatch.setattr(oauth, "_limited", lambda *args: None)
    monkeypatch.setattr(oauth, "_global_limit", lambda *args: None)
    with connect() as db:
        existing = db.execute("select count(*) as n from authoring_oauth_clients").fetchone()["n"]
    monkeypatch.setattr(oauth, "MAX_OAUTH_CLIENTS", existing + 1)
    client = TestClient(app.app)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: register(client), range(2)))
    assert sorted(r.status_code for r in responses) == [201, 503]
    client_id = next(r.json()["client_id"] for r in responses if r.status_code == 201)
    with connect() as db:
        assert db.execute("select 1 from authoring_oauth_clients where id=%s", (client_id,)).fetchone()


def test_cleanup_only_expired_records_preserves_clients_and_active_tokens(creator, monkeypatch):  # noqa: F811
    monkeypatch.setattr("core.request_limits.rate_allowed", lambda *args: True)
    client_id, request_expired, request_active = uuid.uuid4().hex, uuid.uuid4(), uuid.uuid4()
    grant_expired, grant_code, grant_access, grant_refresh = (uuid.uuid4() for _ in range(4))
    with connect() as db:
        db.execute("insert into authoring_oauth_clients(id,name,redirect_uris) values(%s,'test',%s)",
                   (client_id, Jsonb(["http://127.0.0.1/cb"])))
        db.execute("insert into authoring_oauth_requests(id,client_id,data,expires_at) values "
                   "(%s,%s,'{}',now()-interval '1 hour'),(%s,%s,'{}',now()+interval '1 hour')",
                   (request_expired, client_id, request_active, client_id))
        for grant_id in (grant_expired, grant_code, grant_access, grant_refresh):
            db.execute("""insert into authoring_oauth_grants(id,user_id,client_id,scopes,redirect_uri,challenge,resource,
              code_expires,access_expires,refresh_expires) values(%s,%s,%s,'[]','redirect','challenge','resource',
              now()-interval '1 hour',now()-interval '1 hour',now()-interval '1 hour')""",
                       (grant_id, creator["uid"], client_id))
        db.execute("update authoring_oauth_grants set code_hash='code-active',code_expires=now()+interval '1 hour' where id=%s", (grant_code,))
        db.execute("update authoring_oauth_grants set access_hash='access-active',access_expires=now()+interval '1 hour' where id=%s", (grant_access,))
        db.execute("update authoring_oauth_grants set refresh_hash='refresh-active',refresh_expires=now()+interval '1 hour' where id=%s", (grant_refresh,))
        db.execute("insert into authoring_oauth_refresh_history values('expired-history',%s),('active-history',%s)",
                   (grant_expired, grant_refresh))
        oauth._cleanup_expired(db)
    with connect() as db:
        assert db.execute("select 1 from authoring_oauth_clients where id=%s", (client_id,)).fetchone()
        assert not db.execute("select 1 from authoring_oauth_requests where id=%s", (request_expired,)).fetchone()
        assert db.execute("select 1 from authoring_oauth_requests where id=%s", (request_active,)).fetchone()
        assert not db.execute("select 1 from authoring_oauth_grants where id=%s", (grant_expired,)).fetchone()
        for grant_id in (grant_code, grant_access, grant_refresh):
            assert db.execute("select 1 from authoring_oauth_grants where id=%s", (grant_id,)).fetchone()
        assert not db.execute("select 1 from authoring_oauth_refresh_history where token_hash='expired-history'").fetchone()
        assert db.execute("select 1 from authoring_oauth_refresh_history where token_hash='active-history'").fetchone()


def test_consent_and_grant_caps_preserve_existing_authorizations(creator, monkeypatch):  # noqa: F811
    monkeypatch.setattr(oauth, "_limited", lambda *args: None)
    monkeypatch.setattr(oauth, "_global_limit", lambda *args: None)
    monkeypatch.setattr(oauth, "MAX_PENDING_CONSENTS", 1)
    monkeypatch.setattr(oauth, "MAX_ACTIVE_GRANTS", 1)
    monkeypatch.setattr(auth, "user_from_token", lambda _: creator["user"])
    client = TestClient(app.app)
    registration = register(client).json()
    params = dict(client_id=registration["client_id"], redirect_uri="http://127.0.0.1:23456/callback",
                  response_type="code", scope="authoring:read", resource=oauth.resource(),
                  code_challenge_method="S256", code_challenge="a" * 43, ignored="discard")
    response = client.get("/oauth/authoring/authorize", params=params)
    assert response.status_code == 200
    assert client.get("/oauth/authoring/authorize", params=params).status_code == 429
    request_id = re.search("name='request_id' value='([^']+)'", response.text)[1]
    csrf = re.search("name='csrf' value='([^']+)'", response.text)[1]
    with connect() as db:
        row = db.execute("select data from authoring_oauth_requests where id=%s", (request_id,)).fetchone()
        assert "ignored" not in row["data"]
        db.execute("""insert into authoring_oauth_grants(id,user_id,client_id,scopes,redirect_uri,challenge,resource,refresh_hash,refresh_expires)
          values(%s,%s,%s,'[]','redirect','challenge','resource','existing-refresh',now()+interval '1 hour')""",
                   (uuid.uuid4(), creator["uid"], registration["client_id"]))
    consent = client.post("/oauth/authoring/authorize", data=dict(request_id=request_id, csrf=csrf, decision="allow"))
    assert consent.status_code == 429
    with connect() as db:
        assert db.execute("select 1 from authoring_oauth_requests where id=%s", (request_id,)).fetchone()
        assert db.execute("select 1 from authoring_oauth_grants where refresh_hash='existing-refresh'").fetchone()


def test_old_clients_cleanup_preserves_active_requests_and_grants(creator, monkeypatch):  # noqa: F811
    monkeypatch.setattr("core.request_limits.rate_allowed", lambda *args: True)
    old_empty, old_pending, old_grant, young = (uuid.uuid4().hex for _ in range(4))
    with connect() as db:
        for cid in (old_empty, old_pending, old_grant, young):
            db.execute("insert into authoring_oauth_clients(id,name,redirect_uris,created_at) "
                       "values(%s,'test','[]',now()-(%s * interval '1 day'))", (cid, 10 if cid == young else 91))
        db.execute("insert into authoring_oauth_requests(id,client_id,data) values(%s,%s,'{}')", (uuid.uuid4(), old_pending))
        db.execute("""insert into authoring_oauth_grants(id,user_id,client_id,scopes,redirect_uri,challenge,resource,
          refresh_hash,refresh_expires) values(%s,%s,%s,'[]','r','c','resource',%s,now()+interval '1 day')""",
                   (uuid.uuid4(), creator["uid"], old_grant, uuid.uuid4().hex))
        oauth._cleanup_expired(db)
    with connect() as db:
        assert not db.execute("select 1 from authoring_oauth_clients where id=%s", (old_empty,)).fetchone()
        for cid in (old_pending, old_grant, young):
            assert db.execute("select 1 from authoring_oauth_clients where id=%s", (cid,)).fetchone()


def test_cleanup_cannot_delete_client_during_authorization(creator, monkeypatch):  # noqa: F811
    monkeypatch.setattr(oauth, "_limited", lambda *args: None)
    monkeypatch.setattr("core.request_limits.rate_allowed", lambda *args: True)
    monkeypatch.setattr(auth, "user_from_token", lambda _: creator["user"])
    started, finished = threading.Event(), threading.Event()

    def pause_after_client_lock(name, maximum):
        if name == "authorize":
            started.set()
            assert finished.wait(10)

    monkeypatch.setattr(oauth, "_global_limit", pause_after_client_lock)
    cid = uuid.uuid4().hex
    with connect() as db:
        db.execute("insert into authoring_oauth_clients(id,name,redirect_uris,created_at) "
                   "values(%s,'test',%s,now()-interval '91 days')", (cid, Jsonb(["http://127.0.0.1:23456/callback"])))
    params = dict(client_id=cid, redirect_uri="http://127.0.0.1:23456/callback", response_type="code",
                  scope="authoring:read", resource=oauth.resource(), code_challenge_method="S256", code_challenge="a" * 43)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(TestClient(app.app).get, "/oauth/authoring/authorize", params=params)
        assert started.wait(10)
        try:
            with connect() as db:
                oauth._cleanup_expired(db)
        finally:
            finished.set()
        assert pending.result(timeout=10).status_code == 200
    with connect() as db:
        assert db.execute("select 1 from authoring_oauth_clients where id=%s", (cid,)).fetchone()
        assert db.execute("select 1 from authoring_oauth_requests where client_id=%s", (cid,)).fetchone()


def test_refresh_history_limit_and_replay_detection(creator, monkeypatch):  # noqa: F811
    monkeypatch.setattr(oauth, "_limited", lambda *args: None)
    monkeypatch.setattr(oauth, "_global_limit", lambda *args: None)
    monkeypatch.setattr(oauth, "MAX_REFRESH_HISTORY", 2)
    cid, gid, previous, current = uuid.uuid4().hex, uuid.uuid4(), uuid.uuid4().hex, uuid.uuid4().hex
    with connect() as db:
        db.execute("insert into authoring_oauth_clients(id,name,redirect_uris) values(%s,'test','[]')", (cid,))
        db.execute("""insert into authoring_oauth_grants(id,user_id,client_id,scopes,redirect_uri,challenge,resource,
          refresh_hash,refresh_expires) values(%s,%s,%s,%s,'r','c',%s,%s,now()+interval '1 day')""",
                   (gid, creator["uid"], cid, Jsonb(["authoring:read"]), oauth.resource(), oauth.digest(current)))
        db.execute("insert into authoring_oauth_refresh_history values(%s,%s)", (oauth.digest(previous), gid))
    client = TestClient(app.app)
    fields = dict(grant_type="refresh_token", refresh_token=current, client_id=cid, resource=oauth.resource())
    renewed = client.post("/oauth/authoring/token", data=fields)
    assert renewed.status_code == 200
    fields["refresh_token"] = renewed.json()["refresh_token"]
    blocked = client.post("/oauth/authoring/token", data=fields)
    assert blocked.status_code == 400 and blocked.json()["error"] == "invalid_grant"
    assert "重新授权" in blocked.json()["error_description"]
    oauth.verify_bearer(renewed.json()["access_token"])
    fields["refresh_token"] = previous
    assert client.post("/oauth/authoring/token", data=fields).status_code == 400
    with connect() as db:
        assert db.execute("select revoked_at is not null as revoked from authoring_oauth_grants where id=%s", (gid,)).fetchone()["revoked"]
        assert db.execute("select count(*) as n from authoring_oauth_refresh_history where grant_id=%s", (gid,)).fetchone()["n"] == 2


def test_concurrent_refresh_does_not_skip_history_cap_or_replay_check(creator, monkeypatch):  # noqa: F811
    monkeypatch.setattr(oauth, "_limited", lambda *args: None)
    monkeypatch.setattr(oauth, "_global_limit", lambda *args: None)
    monkeypatch.setattr(oauth, "MAX_REFRESH_HISTORY", 1)
    cid, gid, token = uuid.uuid4().hex, uuid.uuid4(), uuid.uuid4().hex
    with connect() as db:
        db.execute("insert into authoring_oauth_clients(id,name,redirect_uris) values(%s,'test','[]')", (cid,))
        db.execute("""insert into authoring_oauth_grants(id,user_id,client_id,scopes,redirect_uri,challenge,resource,
          refresh_hash,refresh_expires) values(%s,%s,%s,%s,'r','c',%s,%s,now()+interval '1 day')""",
                   (gid, creator["uid"], cid, Jsonb(["authoring:read"]), oauth.resource(), oauth.digest(token)))
    fields = dict(grant_type="refresh_token", refresh_token=token, client_id=cid, resource=oauth.resource())
    client = TestClient(app.app)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post("/oauth/authoring/token", data=fields), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 400]
    with connect() as db:
        assert db.execute("select count(*) as n from authoring_oauth_refresh_history where grant_id=%s", (gid,)).fetchone()["n"] == 1
        assert db.execute("select revoked_at is not null as revoked from authoring_oauth_grants where id=%s", (gid,)).fetchone()["revoked"]
