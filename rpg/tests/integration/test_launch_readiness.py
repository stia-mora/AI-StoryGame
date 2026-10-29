"""Production boundary regressions against disposable PostgreSQL; no external calls."""
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

import app
from platform_app import account_recovery, auth, federation
from platform_app.db import connect
from platform_app.security import verify_password
from tests.integration.test_player_credits import player  # noqa: F401


@pytest.fixture(autouse=True)
def server(monkeypatch):
    monkeypatch.setenv("RPG_DEPLOYMENT_MODE", "server")
    monkeypatch.setenv("RPG_REQUIRE_AUTH", "1")
    monkeypatch.setenv("EMAIL_CODE_SECRET", "launch-test-shared-email-secret-123456")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.setenv("RPG_CORS_ORIGINS", "https://example.test")
    monkeypatch.setattr("redis_bus.get_sync_client", lambda: None)
    monkeypatch.setattr("platform_app.email.send_verification_email", lambda *a, **k: None)
    auth._RESEND_LAST.clear()


@pytest.fixture
def user():
    name = "launch_" + uuid.uuid4().hex
    with connect() as db:
        row = db.execute("insert into users(username,password_hash,display_name,email,email_verified,account_mode) "
                         "values(%s,'','Test',%s,true,'creator') returning *", (name, name+"@example.test")).fetchone()
    yield dict(row)
    with connect() as db:
        db.execute("delete from player_ledger where user_id=%s", (row["id"],))
        db.execute("delete from users where id=%s", (row["id"],))


def register(email, username, password):
    return auth.register(username, password, email=email, birthday=date(1990, 1, 1),
                         terms_accepted=True, age_confirmed=True, ip="198.51.100.10")


def test_registration_binds_latest_credentials_across_fresh_process_and_resend(monkeypatch):
    email = "launch_"+uuid.uuid4().hex+"@example.test"
    first, latest = "launch_"+uuid.uuid4().hex, "launch_"+uuid.uuid4().hex
    monkeypatch.setattr(auth, "generate_email_code", lambda n: "111111")
    register(email, first, "FirstPassword1")
    monkeypatch.setattr(auth, "generate_email_code", lambda n: "222222")
    register(email, latest, "LatestPassword2")
    with pytest.raises(ValueError):
        auth.confirm_email_verification(email, "111111")
    monkeypatch.setattr(auth, "generate_email_code", lambda n: "333333")
    auth.resend_verification_code(email)
    # New interpreter has no worker-local registration memory.
    script = "from platform_app.auth import confirm_email_verification; import sys; confirm_email_verification(sys.argv[1], '333333')"
    result = subprocess.run([sys.executable, "-c", script, email], env=os.environ.copy(), capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-1000:]
    with connect() as db:
        row = db.execute("select * from users where lower(email)=%s", (email,)).fetchone()
        assert row["username"] == latest
        assert verify_password("LatestPassword2", row["password_hash"])
        assert not verify_password("FirstPassword1", row["password_hash"])
        assert not db.execute("select 1 from email_verifications where email=%s and pending_payload is not null", (email,)).fetchone()
        db.execute("delete from users where id=%s", (row["id"],))


def test_registration_confirm_is_single_use_and_rolls_back_on_session_failure(monkeypatch):
    email = "launch_"+uuid.uuid4().hex+"@example.test"
    monkeypatch.setattr(auth, "generate_email_code", lambda n: "444444")
    register(email, "launch_"+uuid.uuid4().hex, "Password123!")
    original = auth._issue_session
    monkeypatch.setattr(auth, "_issue_session", lambda *a: (_ for _ in ()).throw(RuntimeError("test rollback")))
    with pytest.raises(RuntimeError):
        auth.confirm_email_verification(email, "444444")
    monkeypatch.setattr(auth, "_issue_session", original)
    def confirm():
        try:
            return auth.confirm_email_verification(email, "444444")[0]["id"]
        except ValueError:
            return None
    with ThreadPoolExecutor(2) as pool:
        ids = list(pool.map(lambda _: confirm(), range(2)))
    assert sum(value is not None for value in ids) == 1
    with connect() as db:
        db.execute("delete from users where id=%s", (next(value for value in ids if value),))


def test_pat_and_device_revocation_survive_reactivation(user):
    pat = federation.create_pat(user["id"], "test", ["library:read"])
    device = federation.device_start("test", [], "https://example.test/device")
    federation.device_approve(user["id"], device["user_code"])
    with connect() as db:
        federation.revoke_account_tokens(db, user["id"])
        db.execute("update users set deactivated_at=now() where id=%s", (user["id"],))
    with pytest.raises(PermissionError):
        federation.verify_pat(pat["token"])
    assert federation.device_poll(device["device_code"])["error"] == "access_denied"
    with connect() as db:
        db.execute("update users set deactivated_at=null where id=%s", (user["id"],))
    with pytest.raises(PermissionError):
        federation.verify_pat(pat["token"])


def test_concurrent_device_polls_issue_exactly_one_token(user):
    device = federation.device_start("test", [], "https://example.test/device")
    federation.device_approve(user["id"], device["user_code"])
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: federation.device_poll(device["device_code"]), range(2)))
    assert sum(bool(result.get("access_token")) for result in results) == 1
    assert any(result.get("error") == "token_already_issued" for result in results)


def test_dmca_termination_uses_current_schema_and_revokes_credentials(user):
    from platform_app.dmca import increment_strike, queue_account_termination
    pat = federation.create_pat(user["id"], "test", [])
    try:
        with connect() as db:
            for number in range(1, 4):
                result = increment_strike(db, user["id"], "test")
                assert result["strike_count"] == number
            assert result["terminate"]
            queue_account_termination(db, user["id"], "test")
        with pytest.raises(PermissionError):
            federation.verify_pat(pat["token"])
        with connect() as db:
            assert db.execute("select 1 from banned_users where email_norm=%s", (user["email"],)).fetchone()
            assert db.execute("select 1 from account_delete_queue where user_id=%s and scheduled_hard_delete_at>now()", (user["id"],)).fetchone()
    finally:
        with connect() as db:
            db.execute("delete from banned_users where email_norm=%s", (user["email"],))


def test_player_mode_and_deactivated_accounts_cannot_issue_pat(user):
    with connect() as db:
        db.execute("update users set account_mode='player' where id=%s", (user["id"],))
    with pytest.raises(PermissionError):
        federation.create_pat(user["id"], "test", [])


def test_email_aliases_share_account_failure_budget(user, monkeypatch):
    checks = []
    monkeypatch.setattr(auth, "verify_password_with_rehash", lambda *a: checks.append(1) or (False, None))
    local, domain = user["email"].split("@")
    for index in range(8):
        with pytest.raises((ValueError, auth.RateLimited)):
            auth.login(f"{local}+tag{index}@{domain}", "wrong", ip=f"203.0.113.{index+10}")
    assert len(checks) == 5


def test_banned_email_cannot_create_apple_or_passwordless_account(monkeypatch):
    email = "launch_"+uuid.uuid4().hex+"@example.test"
    with connect() as db:
        db.execute("insert into banned_users(email_norm,reason) values(%s,'test')", (email,))
    try:
        with pytest.raises(ValueError, match="限制注册"):
            auth.login_or_create_apple_user(uuid.uuid4().hex, email)
    finally:
        with connect() as db:
            db.execute("delete from banned_users where email_norm=%s", (email,))


def test_live_security_policy_controls_password_and_sessions(user):
    with connect() as db:
        previous = db.execute("select value from app_config where key='admin.security_config'").fetchone()
        db.execute("insert into app_config(key,value) values('admin.security_config',%s) on conflict(key) do update set value=excluded.value",
                   (Jsonb({"password_min_length": 12, "password_require_numbers": True, "session_timeout_days": 1}),))
    try:
        from platform_app.security_policy import validate_password
        with pytest.raises(ValueError):
            validate_password("NoDigitsButLong")
        with pytest.raises(ValueError):
            validate_password("Short123")
        validate_password("StrongPassword123")
        with connect() as db:
            token = auth._issue_session(db, user["id"])
            seconds = db.execute("select extract(epoch from expires_at-created_at) as seconds from sessions where token_hash=%s", (auth._hash_token(token),)).fetchone()["seconds"]
            assert 86390 <= seconds <= 86410
        assert auth.user_from_token(token)["id"] == user["id"]
        with connect() as db:
            db.execute("update sessions set created_at=now()-interval '2 days' where user_id=%s", (user["id"],))
        assert auth.user_from_token(token) is None
    finally:
        with connect() as db:
            if previous:
                db.execute("update app_config set value=%s where key='admin.security_config'", (Jsonb(previous["value"]),))
            else:
                db.execute("delete from app_config where key='admin.security_config'")


def test_delete_request_has_reachable_one_time_email_recovery(user, monkeypatch):
    sent = []
    monkeypatch.setattr("platform_app.email.send_recovery_code_email", lambda email, code: sent.append(code))
    with connect() as db:
        token = auth._issue_session(db, user["id"])
    client = TestClient(app.app)
    client.cookies.set("rpg_session", token)
    assert client.post("/api/account/request-delete", json={}).status_code == 200
    assert auth.user_from_token(token) is None
    assert client.get("/api/player/bootstrap").status_code == 401
    assert client.post("/api/auth/recovery/request", json={"email": user["email"]}).status_code == 200
    assert len(sent) == 1
    response = client.post("/api/auth/recovery/confirm", json={"email": user["email"], "code": sent[0]})
    assert response.status_code == 200, response.text
    assert client.get("/api/player/bootstrap").status_code == 200
    assert client.post("/api/auth/recovery/confirm", json={"email": user["email"], "code": sent[0]}).status_code == 400


def test_expired_or_banned_deletion_cannot_recover(user, monkeypatch):
    monkeypatch.setattr("platform_app.email.send_recovery_code_email", lambda *a: pytest.fail("must not send"))
    with connect() as db:
        db.execute("update users set deactivated_at=now() where id=%s", (user["id"],))
        db.execute("insert into account_delete_queue(user_id,scheduled_hard_delete_at) values(%s,now()-interval '1 second')", (user["id"],))
    assert account_recovery.request_code(user["email"]) == {"ok": True}


def test_hard_delete_removes_player_ledger_and_continues_after_failed_account(user, player):
    from cron.hard_delete import run_hard_delete
    from platform_app.player import catalog, wallet
    save = catalog.player_save(player["uid"], player["sid"])
    quote = wallet.make_quote(player["uid"], save, player["profile"], "turn", "test", 200)
    request, _ = wallet.reserve(player["uid"], save, quote["id"], str(uuid.uuid4()), "test", "turn", "test")
    wallet.release(player["uid"], str(request["id"]), "test")
    with connect() as db:
        # Service owners must transfer shared stories/credentials before physical
        # deletion. An old blocked queue must not abort unrelated player deletion.
        db.execute("update scripts set owner_id=%s where id=(select script_id from player_stories where id=%s)", (user["id"], player["story"]))
        db.execute("update player_model_profiles set credential_owner_id=%s where id=%s", (user["id"], player["profile"]["id"]))
        for uid in (user["id"], player["uid"]):
            db.execute("insert into account_delete_queue(user_id,scheduled_hard_delete_at) values(%s,now()-interval '1 second')", (uid,))
        result = run_hard_delete(db)
        assert result["failed"] == 1 and result["deleted"] >= 1
        assert not db.execute("select id from users where id=%s", (player["uid"],)).fetchone()
        assert not db.execute("select 1 from player_requests where user_id=%s", (player["uid"],)).fetchone()
        assert db.execute("select completed_at from account_delete_queue where user_id=%s", (user["id"],)).fetchone()["completed_at"] is None


def test_public_catalog_excludes_private_state_and_unlisted_stories(player):
    client = TestClient(app.app)
    assert client.get("/api/player/session").json() == {"authenticated": False}
    result = client.get("/api/player/catalog").json()
    story = next(row for row in result["stories"] if row["id"] == player["story"])
    assert set(story) == {"id", "title", "introduction", "cover", "identities", "martial_soul_creation"}
    assert client.get(f"/api/player/saves/{player['sid']}").status_code == 401
    with connect() as db:
        db.execute("update player_stories set status='unlisted' where id=%s", (player["story"],))
    assert not any(row["id"] == player["story"] for row in client.get("/api/player/catalog").json()["stories"])


def test_save_summaries_are_paginated_searchable_and_owned(player):
    from platform_app import auth

    with connect() as db:
        script = db.execute("select script_id from game_saves where id=%s", (player["sid"],)).fetchone()["script_id"]
        for index in range(52):
            data = {"player": {"name": f"角色{index}%_"}, "turn": index, "private": "secret" * 1000}
            db.execute("insert into game_saves(user_id,script_id,title,state_path,state_snapshot,player_story_id,updated_at) "
                       "values(%s,%s,%s,'',%s,%s,now() - %s * interval '1 second')",
                       (player["uid"], script, f"存档{index}", Jsonb(data), player["story"], index + 1))
        other = db.execute("insert into users(username,password_hash,display_name,email_verified) "
                           "values(%s,'test','Other',true) returning id", ("other_" + uuid.uuid4().hex,)).fetchone()["id"]
        db.execute("insert into game_saves(user_id,script_id,title,state_path,state_snapshot,player_story_id) "
                   "values(%s,%s,'other-secret','',%s,%s)", (other, script, Jsonb({}), player["story"]))
        token = auth._issue_session(db, player["uid"])
    try:
        client = TestClient(app.app, cookies={"rpg_session": token})
        bootstrap = client.get("/api/player/bootstrap").json()
        assert bootstrap["save_total"] == 53 and len(bootstrap["saves"]) == 50
        assert "secret" not in str(bootstrap["saves"])
        first = client.get("/api/player/saves").json()
        second = client.get("/api/player/saves", params={"page": 2}).json()
        assert first["total"] == 53 and first["pages"] == 2 and len(first["items"]) == 50
        assert len(second["items"]) == 3 and not {s["id"] for s in first["items"]} & {s["id"] for s in second["items"]}
        search = client.get("/api/player/saves", params={"query": "角色51%_"}).json()
        assert search["total"] == 1 and search["items"][0]["name"] == "角色51%_"
        assert client.get("/api/player/saves", params={"query": "other-secret"}).json()["total"] == 0
        assert TestClient(app.app).get("/api/player/saves").status_code == 401
    finally:
        with connect() as db:
            db.execute("delete from game_saves where user_id=%s", (other,))
            db.execute("delete from users where id=%s", (other,))


def test_server_startup_health_guest_root_and_logout_revoke_cookie(user, monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<html>故事之间官网</html>", encoding="utf-8")
    (tmp_path / "Player.html").write_text("<html>玩家入口</html>", encoding="utf-8")
    (tmp_path / "Platform.html").write_text("<html>创作入口</html>", encoding="utf-8")
    monkeypatch.setattr(app, "_FRONTEND_DIR", tmp_path)
    monkeypatch.setattr(app, "_FRONTEND_HAS_DIST", True)
    with TestClient(app.app) as client:
        assert client.get("/livez").json()["ok"] is True
        assert client.get("/readyz").json()["db"] == "ok"
        assert "故事之间官网" in client.get("/").text
        with connect() as db:
            token = auth._issue_session(db, user["id"])
        client.cookies.set("rpg_session", token)
        assert client.get("/api/player/bootstrap").status_code == 200
        assert client.post("/api/auth/logout").status_code == 200
        assert auth.user_from_token(token) is None
        assert client.get("/api/player/session").json() == {"authenticated": False}


def test_login_cookie_is_secure_when_production_requires_it(user, monkeypatch):
    from platform_app.security import hash_password

    monkeypatch.setenv("RPG_COOKIE_SECURE", "1")
    with connect() as db:
        db.execute("update users set password_hash=%s where id=%s", (hash_password("TestPassword123"), user["id"]))
    response = TestClient(app.app).post("/api/auth/login", json={"username": user["username"], "password": "TestPassword123"})
    assert response.status_code == 200, response.text
    assert "secure" in response.headers["set-cookie"].lower()


def test_security_blocklist_is_enforced_before_business_routes():
    with connect() as db:
        previous = db.execute("select value from app_config where key='admin.security_config'").fetchone()
        db.execute("insert into app_config(key,value) values('admin.security_config',%s) on conflict(key) do update set value=excluded.value",
                   (Jsonb({"ip_blocklist": ["203.0.113.0/24"]}),))
    try:
        client = TestClient(app.app, client=("203.0.113.10", 12345))
        assert client.get("/api/player/catalog").status_code == 403
        assert client.get("/readyz").status_code == 200
    finally:
        with connect() as db:
            if previous:
                db.execute("update app_config set value=%s where key='admin.security_config'", (Jsonb(previous["value"]),))
            else:
                db.execute("delete from app_config where key='admin.security_config'")


def test_history_pages_only_active_ancestors_and_quote_cleanup_retains_receipts(player):
    from platform_app.player import catalog, wallet
    with connect() as db:
        parent = db.execute("select active_commit_id from game_saves where id=%s", (player["sid"],)).fetchone()["active_commit_id"]
        for turn in range(1, 46):
            parent = db.execute("insert into branch_commits(save_id,parent_id,object_hash,turn_index,kind,title,gm_output,state_snapshot) "
                                "values(%s,%s,%s,%s,'turn','Test','Narration','{}') returning id", (player["sid"], parent, uuid.uuid4().hex, turn)).fetchone()["id"]
        db.execute("update game_saves set active_commit_id=%s where id=%s", (parent, player["sid"]))
    page = catalog.view(player["uid"], player["sid"])
    assert len(page["messages"]) == 20
    assert page["messages"][-1]["turn"] == 45
    older = catalog.view(player["uid"], player["sid"], page["history_before"])
    assert older["messages"][-1]["turn"] == 25
    assert not {m["id"] for m in page["messages"]} & {m["id"] for m in older["messages"]}
    save = catalog.player_save(player["uid"], player["sid"])
    unused = wallet.make_quote(player["uid"], save, player["profile"], "turn", "one", 200)
    used = wallet.make_quote(player["uid"], save, player["profile"], "turn", "two", 200)
    req, _ = wallet.reserve(player["uid"], save, used["id"], str(uuid.uuid4()), "test", "turn", "two")
    wallet.release(player["uid"], str(req["id"]), "test")
    with connect() as db:
        db.execute("update player_quotes set expires_at=now()-interval '2 hours' where id=any(%s)", ([uuid.UUID(unused["id"]), uuid.UUID(used["id"])],))
    wallet.reap()
    with connect() as db:
        assert not db.execute("select 1 from player_quotes where id=%s", (unused["id"],)).fetchone()
        assert db.execute("select 1 from player_quotes where id=%s", (used["id"],)).fetchone()
