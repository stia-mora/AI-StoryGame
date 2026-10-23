"""Real PostgreSQL transaction tests; isolated fixtures, no provider calls."""

import copy
import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from psycopg.types.json import Jsonb

import app
from platform_app.db import connect
from platform_app.player import catalog, wallet
from platform_app.player.meter import Run, active_run, phase


@pytest.fixture
def player(tmp_path):
    from platform_app import branches
    from state import DEFAULT_STATE

    name = "player_test_" + uuid.uuid4().hex
    with connect() as db:
        u = db.execute(
            "insert into users(username,password_hash,display_name,email_verified) values(%s,'test','Test',true) returning *",
            (name,),
        ).fetchone()
        s = db.execute(
            "insert into scripts(owner_id,title,review_status) values(%s,'测试故事','reviewed') returning id",
            (u["id"],),
        ).fetchone()
        p = db.execute(
            "insert into player_model_profiles(name,credential_owner_id,api_id,model,max_output) values('Test',%s,'test','text',1024) returning *",
            (u["id"],),
        ).fetchone()
        story = db.execute(
            "insert into player_stories(script_id,profile_id,title,status,identities) values(%s,%s,'测试故事','published','[]') returning id",
            (s["id"], p["id"]),
        ).fetchone()
        data = copy.deepcopy(DEFAULT_STATE)
        data["history"] = []
        g = db.execute(
            "insert into game_saves(user_id,script_id,title,state_path,state_snapshot,player_story_id) values(%s,%s,'Test','',%s,%s) returning *",
            (u["id"], s["id"], Jsonb(data), story["id"]),
        ).fetchone()
    snapshot = tmp_path / "state.json"
    import json

    snapshot.write_text(json.dumps(data), encoding="utf-8")
    branches.seed_tree(g["id"], str(snapshot))
    branches.activate_save(u["id"], g["id"])
    yield dict(uid=u["id"], sid=g["id"], story=story["id"], profile=dict(p), user=dict(u))
    app._invalidate_user_cache(u)
    with connect() as db:
        db.execute(
            "delete from player_llm_calls where request_id in (select id from player_requests where user_id=%s)",
            (u["id"],),
        )
        db.execute("delete from player_ledger where user_id=%s", (u["id"],))
        db.execute("delete from player_requests where user_id=%s", (u["id"],))
        db.execute("delete from player_quotes where user_id=%s", (u["id"],))
        db.execute("delete from player_redemptions where user_id=%s", (u["id"],))
        db.execute("delete from game_saves where user_id=%s", (u["id"],))
        db.execute("delete from player_stories where id=%s", (story["id"],))
        db.execute("delete from player_model_profiles where id=%s", (p["id"],))
        db.execute("delete from scripts where id=%s", (s["id"],))
        db.execute("delete from users where id=%s", (u["id"],))


def reservation(p, message="行动"):
    save = catalog.player_save(p["uid"], p["sid"])
    quote = wallet.make_quote(p["uid"], save, p["profile"], "turn", message, 200)
    rid = str(uuid.uuid4())
    req, replay = wallet.reserve(
        p["uid"], save, quote["id"], rid, "logical-action", "turn", message
    )
    return req, quote, save


def test_credit_history_pages_filters_literal_query_and_owner(player):
    from datetime import date
    from platform_app.player.ledger import history

    with connect() as db:
        for index in range(23):
            db.execute("insert into player_ledger(user_id,kind,reason,created_at) values(%s,%s,%s,%s)",
                       (player["uid"], "grant" if index % 2 else "redeem", f"测试%_发放 {index}", "2026-10-22T16:30:00Z"))
    first = history(player["uid"], page_size=10)
    second = history(player["uid"], page=2, page_size=10)
    assert first["total"] == 23 and first["pages"] == 3
    assert len(first["items"]) == len(second["items"]) == 10
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}
    filtered = history(player["uid"], kind="grant", query="%_", date_from=date(2026, 10, 23), date_to=date(2026, 10, 23))
    assert filtered["total"] == 11
    assert history(player["uid"], date_to=date(2026, 10, 22))["total"] == 0
    assert history(player["uid"], query="不存在")["total"] == 0
    assert history(-1)["total"] == 0
    assert history(player["uid"], page=999)["page"] == 3
    with pytest.raises(HTTPException, match="开始日期"):
        history(player["uid"], date_from=date(2026, 10, 24), date_to=date(2026, 10, 23))


def test_custom_initialization_is_free_and_keeps_story_defaults(player):
    from platform_app.api.player import Create, create

    view = create(Create(story_id=player["story"], name="小镇居民", custom_identity="修理对讲机的学生", background="和朋友一起调查街灯异常"), user=player["user"])
    save = catalog.player_save(player["uid"], view["save"]["id"])
    assert view["status"]["name"] == "小镇居民"
    assert not view["has_opening"]
    assert "修理对讲机的学生" in str(save["state_snapshot"])
    with connect() as db:
        assert not db.execute("select id from player_requests where user_id=%s", (player["uid"],)).fetchall()
    with pytest.raises(HTTPException, match="角色名字"):
        create(Create(story_id=player["story"], name="  ", custom_identity="学生"), user=player["user"])


def test_free_creation_seeds_selected_soul_in_root_and_kb_without_awarding_it(player):
    from platform_app.api.player import Create, create
    from kb.save_kb import materialize

    defaults = {"character_creation": {"martial_soul": {
        "enabled": True, "choices": [{"name": "铁剑"}],
        "innate_power_min": 4, "innate_power_max": 4,
    }}}
    with connect() as db:
        db.execute("update player_stories set identities=%s,defaults=%s where id=%s", (
            Jsonb([{"id": "native", "name": "村中少年"}]), Jsonb(defaults), player["story"],
        ))
    view = create(Create(story_id=player["story"], name="沈砚", identity_id="native",
        martial_soul={"mode": "custom", "name": "青羽弓"}), user=player["user"])
    save = catalog.player_save(player["uid"], view["save"]["id"])
    expected = {"kind": "martial_soul", "mode": "custom", "name": "青羽弓",
        "innate_soul_power": 4, "completed": False}
    assert save["state_snapshot"]["player_setup"] == expected
    with connect() as db:
        root = db.execute("select state_snapshot from branch_commits where id=%s", (save["active_commit_id"],)).fetchone()
        assert root["state_snapshot"]["player_setup"] == expected
        assert materialize(db, save["id"], save["active_commit_id"])["player_setup"] == expected
        assert not db.execute("select id from player_requests where user_id=%s", (player["uid"],)).fetchall()
    assert view["character_setup"] == {"mode": "custom", "name": "青羽弓", "completed": False}
    assert not any(a["name"] in {"武魂", "魂力"} for a in view["status"]["attributes"])
    assert not view["has_opening"]


def test_incomplete_awakening_cannot_commit_or_charge_even_on_partial_save(player):
    from platform_app import branches
    save = catalog.player_save(player["uid"], player["sid"])
    q = wallet.make_quote(player["uid"], save, player["profile"], "opening", "", 200)
    req, _ = wallet.reserve(player["uid"], save, q["id"], str(uuid.uuid4()), "wake", "opening", "")
    run = Run(req)
    run.character_setup = {"kind": "martial_soul", "mode": "custom", "name": "青羽弓", "innate_soul_power": 4, "completed": False}
    run.partial = run.committing = True
    token = active_run.set(run)
    try:
        with pytest.raises(ValueError, match="未完整确认"):
            branches.record_runtime_turn("", "你等待觉醒。", user_id=player["uid"], state_data=copy.deepcopy(save["state_snapshot"]))
    finally:
        active_run.reset(token)
        wallet.release(player["uid"], run.id, "觉醒尚未完成")
    fresh = catalog.player_save(player["uid"], player["sid"])
    assert fresh["active_commit_id"] == save["active_commit_id"]
    assert fresh["state_snapshot"] == save["state_snapshot"]
    assert wallet.wallet(player["uid"])["held_micro"] == 0
    assert wallet.wallet(player["uid"])["free_micro"] == 100_000_000


def test_free_creation_cannot_switch_away_from_an_inflight_paid_save(player):
    from platform_app.api.player import Create, create
    from platform_app import runtime
    req, _, save = reservation(player)
    before = runtime.read_runtime(user_id=player["uid"])
    with pytest.raises(HTTPException) as exc:
        create(Create(story_id=player["story"], name="另一个角色", identity_id="native"), user=player["user"])
    assert exc.value.status_code == 409
    assert runtime.read_runtime(user_id=player["uid"])["save_id"] == before["save_id"]
    assert catalog.player_save(player["uid"], player["sid"])["active_commit_id"] == save["active_commit_id"]
    wallet.release(player["uid"], str(req["id"]), "测试完成")


def test_guide_settles_once_without_mutating_branch(player):
    from platform_app.player.guide import commit

    uid, sid = player["uid"], player["sid"]
    save = catalog.player_save(uid, sid)
    before = save["state_snapshot"]
    q = wallet.make_quote(uid, save, player["profile"], "guide", "怎样前进？", 200)
    req, _ = wallet.reserve(
        uid, save, q["id"], str(uuid.uuid4()), "guide-action", "guide", "怎样前进？"
    )
    run = Run(req)
    with phase("guide"):
        run.record(
            str(uuid.uuid4()), "openai", "text", {"prompt_tokens": 200, "completion_tokens": 100}
        )
    receipt = commit(run, "怎样前进？", "先向同行者问路。", ["向同行者问路"])
    assert receipt["charged_micro"] == 600_000
    assert receipt["kind"] == "guide"
    fresh = catalog.player_save(uid, sid)
    assert fresh["active_commit_id"] == save["active_commit_id"]
    assert fresh["state_snapshot"] == before
    assert wallet.wallet(uid)["held_micro"] == 0
    with pytest.raises(HTTPException):
        commit(run, "怎样前进？", "同一答案", [])
    assert wallet.wallet(uid)["free_micro"] == 99_400_000


def test_stopped_guide_cannot_settle_or_change_state(player):
    from platform_app.player.guide import commit

    uid, sid = player["uid"], player["sid"]
    save = catalog.player_save(uid, sid)
    q = wallet.make_quote(uid, save, player["profile"], "guide", "情况如何？", 200)
    req, _ = wallet.reserve(
        uid, save, q["id"], str(uuid.uuid4()), "stopped-guide", "guide", "情况如何？"
    )
    run = Run(req)
    with connect() as db:
        db.execute("update player_requests set stop_requested=true where id=%s", (run.id,))
    with pytest.raises(HTTPException):
        commit(run, "情况如何？", "已得到答案", [])
    wallet.release(uid, run.id)
    assert wallet.wallet(uid)["free_micro"] == 100_000_000
    assert wallet.wallet(uid)["held_micro"] == 0
    assert catalog.player_save(uid, sid)["active_commit_id"] == save["active_commit_id"]


def test_consultation_receipt_never_overwrites_the_game_round_receipt(player):
    from platform_app import branches
    from platform_app.player.guide import commit, history

    req, _, save = reservation(player)
    run = Run(req)
    run.committing = True
    token = active_run.set(run)
    try:
        with phase("reply"):
            run.record(str(uuid.uuid4()), "openai", "text", {"prompt_tokens": 100, "completion_tokens": 50})
        branches.record_runtime_turn("出发", "你抵达了村口。", user_id=player["uid"], state_data=save["state_snapshot"])
    finally:
        active_run.reset(token)
    save = catalog.player_save(player["uid"], player["sid"])
    q = wallet.make_quote(player["uid"], save, player["profile"], "guide", "该做什么？", 200)
    guide_req, _ = wallet.reserve(player["uid"], save, q["id"], str(uuid.uuid4()), "new-guide", "guide", "该做什么？")
    guide_run = Run(guide_req)
    commit(guide_run, "该做什么？", "询问路人。", [])
    visible = catalog.view(player["uid"], player["sid"])
    assert visible["messages"][-1]["receipt"]["request_id"] == run.id
    assert len(visible["messages"]) == 2
    assert history(player["uid"], player["sid"])[0]["request_id"] == guide_run.id


def test_daily_lazy_idempotent_and_existing_accounts_keep_creator(player):
    uid = player["uid"]
    assert player["user"]["account_mode"] == "player"
    assert wallet.wallet(uid)["free_micro"] == 100_000_000
    assert wallet.wallet(uid)["free_micro"] == 100_000_000
    with connect() as db:
        assert (
            db.execute(
                "select count(*) as n from player_ledger where user_id=%s and kind='daily'", (uid,)
            ).fetchone()["n"]
            == 1
        )


def test_quote_uses_complete_foreground_usage_not_saved_debug_cache(player):
    from platform_app.api.player import Quote, quote

    req, _, save = reservation(player)
    run = Run(req)
    with phase("curator"):
        run.record(
            str(uuid.uuid4()), "openai", "text", {"prompt_tokens": 3405, "completion_tokens": 1198}
        )
    with phase("reply"):
        run.record(
            str(uuid.uuid4()), "openai", "text", {"prompt_tokens": 23901, "completion_tokens": 796}
        )
    with connect() as db:
        wallet.settle(
            db, player["uid"], str(req["id"]), save["active_commit_id"], "已保存的有效回复", []
        )
        data = save["state_snapshot"]
        data["last_retrieval"] = "并非再次发送的调试缓存" * 10000
        db.execute(
            "update game_saves set state_snapshot=%s where id=%s", (Jsonb(data), player["sid"])
        )
    result = quote(
        Quote(save_id=player["sid"], kind="turn", message="询问修炼方向"), user=player["user"]
    )
    assert 60_000_000 < result["cap_micro"] < 100_000_000
    assert result["cap_micro"] == result["estimate_micro"] * 2


def test_reserve_replay_and_failure_release(player):
    req, q, save = reservation(player)
    original = wallet.wallet(player["uid"])
    replay, yes = wallet.reserve(
        player["uid"], save, q["id"], str(req["id"]), "logical-action", "turn", "行动"
    )
    assert yes and replay["id"] == req["id"]
    assert wallet.wallet(player["uid"]) == original
    with pytest.raises(HTTPException):
        wallet.reserve(
            player["uid"], save, q["id"], str(req["id"]), "logical-action", "turn", "不同的行动"
        )
    wallet.release(player["uid"], str(req["id"]))
    wallet.release(player["uid"], str(req["id"]))
    assert wallet.wallet(player["uid"])["free_micro"] == 100_000_000
    assert wallet.wallet(player["uid"])["held_micro"] == 0


def test_atomic_commit_and_whole_turn_actual_usage(player, monkeypatch):
    from platform_app import branches

    monkeypatch.setattr("platform_app.branches.runtime.schedule_llm_summary", lambda *a: None)
    req, q, save = reservation(player)
    run = Run(req)
    token = active_run.set(run)
    try:
        run.record(
            str(uuid.uuid4()),
            "openai",
            "m",
            {
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "completion_tokens_details": {"reasoning_tokens": 40},
            },
        )
        run.record(
            str(uuid.uuid4()),
            "vertex_ai",
            "m",
            {"prompt_token_count": 500, "candidates_token_count": 60, "thoughts_token_count": 20},
        )
        with phase("phase_digest"):
            run.record(
                str(uuid.uuid4()),
                "openai",
                "m",
                {"prompt_tokens": 10000, "completion_tokens": 1000},
            )
        run.committing = True
        result = branches.record_runtime_turn(
            "行动", "有效回复", user_id=player["uid"], state_data=save["state_snapshot"]
        )
        assert result["ok"]
    finally:
        active_run.reset(token)
    assert run.receipt["charged_micro"] == 2_220_000
    assert run.receipt["input_tokens"] == 1500
    assert run.receipt["output_tokens"] == 180
    assert wallet.wallet(player["uid"])["held_micro"] == 0
    assert wallet.wallet(player["uid"])["free_micro"] == 97_780_000
    wallet.release(player["uid"], str(req["id"]))
    assert wallet.wallet(player["uid"])["free_micro"] == 97_780_000


def test_insufficient_and_parallel_requests_do_not_overdraw(player):
    with connect() as db:
        wallet.lock_wallet(db, player["uid"])
        db.execute("update player_wallets set free_micro=0 where user_id=%s", (player["uid"],))
    with pytest.raises(HTTPException) as exc:
        reservation(player)
    assert exc.value.status_code == 402
    with connect() as db:
        db.execute(
            "update player_wallets set free_micro=100000000 where user_id=%s", (player["uid"],)
        )

    def attempt(_):
        try:
            return reservation(player)[0]
        except HTTPException:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert len([r for r in results if r]) == 1
    wallet.release(player["uid"], str(next(r for r in results if r)["id"]))
    assert wallet.wallet(player["uid"])["free_micro"] == 100_000_000


def test_midnight_release_drops_expired_free_and_preserves_permanent(player):
    req, _, _ = reservation(player)
    with connect() as db:
        db.execute(
            "update player_requests set free_day=free_day-1,expires_at=now()-interval '1 second' where id=%s",
            (req["id"],),
        )
    wallet.reap(player["uid"])
    w = wallet.wallet(player["uid"])
    assert w["permanent_micro"] == 0 and w["held_micro"] == 0
    assert w["free_micro"] == 100_000_000 - req["free_hold"]


def test_expired_lease_cannot_commit(player):
    req, _, _ = reservation(player)
    with connect() as db:
        db.execute(
            "update player_requests set expires_at=now()-interval '1 second' where id=%s",
            (req["id"],),
        )
    with connect() as db:
        with pytest.raises(HTTPException):
            wallet.lock_request(db, player["uid"], str(req["id"]), player["sid"])
    wallet.reap(player["uid"])


def test_duplicate_concurrent_redemption(player):
    code = uuid.uuid4().hex.upper()
    digest = hashlib.sha256(code.encode()).hexdigest()
    with connect() as db:
        cid = db.execute(
            "insert into player_codes(code_hash,label,amount_micro,max_uses) values(%s,'Test',1234567,2) returning id",
            (digest,),
        ).fetchone()["id"]
    try:

        def redeem(_):
            try:
                wallet.redeem(player["uid"], code)
                return True
            except HTTPException:
                return False

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(redeem, range(3)))
        assert sum(results) == 1
        assert wallet.wallet(player["uid"])["permanent_micro"] == 1234567
    finally:
        with connect() as db:
            db.execute("delete from player_redemptions where code_id=%s", (cid,))
            db.execute("delete from player_codes where id=%s", (cid,))


def test_player_permission_isolation_and_legacy_bypass(player, monkeypatch):
    from fastapi.testclient import TestClient

    from platform_app.api import _deps

    monkeypatch.setattr(_deps, "current_user", lambda request: player["user"])
    client = TestClient(app.app)
    assert client.get("/api/v1/player/bootstrap").status_code == 200
    for path in (
        "/api/v1/platform",
        "/api/v1/scripts",
        "/api/v1/models",
        "/api/v1/chat",
        "/api/v1/admin/player",
    ):
        response = client.post(path, json={}) if path.endswith("chat") else client.get(path)
        assert response.status_code == 403, (path, response.text)
    assert client.get(f"/api/v1/player/saves/{player['sid'] + 100000}").status_code == 404
    assert client.get(f"/api/v1/player/saves/{player['sid'] + 100000}/guide").status_code == 404
    with pytest.raises(HTTPException):
        catalog.require_metered_legacy(player["uid"], player["sid"])


def test_save_failure_rolls_back_commit_and_bill(player, monkeypatch):
    from platform_app import branches

    req, _, save = reservation(player)
    run = Run(req)
    run.committing = True

    def failure(*args, **kwargs):
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(wallet, "settle", failure)
    token = active_run.set(run)
    try:
        with pytest.raises(RuntimeError):
            branches.record_runtime_turn(
                "行动", "有效回复", user_id=player["uid"], state_data=save["state_snapshot"]
            )
    finally:
        active_run.reset(token)
    assert run.receipt is None
    assert (
        catalog.player_save(player["uid"], player["sid"])["active_commit_id"]
        == save["active_commit_id"]
    )
    wallet.release(player["uid"], str(req["id"]))
    assert wallet.wallet(player["uid"])["free_micro"] == 100_000_000


def test_real_midnight_refund_keeps_today_grant_and_long_term_credits(player):
    uid = player["uid"]
    with connect() as db:
        wallet.lock_wallet(db, uid)
        db.execute(
            "update player_wallets set free_micro=3000000,permanent_micro=10000000 where user_id=%s",
            (uid,),
        )
    req, _, _ = reservation(player)
    assert req["permanent_hold"] > 0
    with connect() as db:
        db.execute("update player_wallets set free_day=free_day-1 where user_id=%s", (uid,))
        db.execute(
            "update player_requests set free_day=free_day-1,expires_at=now()-interval '1 second' where id=%s",
            (req["id"],),
        )
    wallet.reap(uid)
    w = wallet.wallet(uid)
    assert (
        w["free_micro"] == 100_000_000
        and w["permanent_micro"] == 10_000_000
        and w["held_micro"] == 0
    )


def test_cap_platform_absorption_missing_usage_and_partial_receipt(player):
    req, _, _ = reservation(player)
    run = Run(req)
    token = active_run.set(run)
    try:
        run.record(
            str(uuid.uuid4()), "openai", "m", {"prompt_tokens": 10000, "completion_tokens": 1000}
        )
        run.record(str(uuid.uuid4()), "openai", "m", None)
        with connect() as db:
            receipt = wallet.settle(
                db, player["uid"], str(req["id"]), None, "已保存的有效部分", [], True
            )
    finally:
        active_run.reset(token)
    assert receipt["charged_micro"] == req["cap_micro"]
    assert receipt["platform_micro"] == 14_000_000 - req["cap_micro"]
    assert receipt["partial"] and receipt["input_tokens"] == 10000


def test_registration_and_login_default_to_player_without_client_escalation():
    from tests.helpers import login_user, make_client, register_user

    client = make_client()
    name = "player_reg_" + uuid.uuid4().hex
    result = register_user(client, username=name, account_mode="player")
    assert result["status"] == 200
    u = result["body"]["user"]
    try:
        assert u["account_mode"] == "player" and u["role"] == "user"
        assert result["body"]["platform"]["next"] == "/play"
        assert client.get("/api/v1/models").status_code == 403
        client.post("/api/v1/auth/logout")
        login = login_user(client, name)
        assert login["status"] == 200 and login["body"]["user"]["account_mode"] == "player"
        assert (
            client.patch(
                f"/api/v1/admin/users/{u['id']}", json={"account_mode": "creator", "role": "admin"}
            ).status_code
            == 403
        )
    finally:
        with connect() as db:
            db.execute("delete from player_ledger where user_id=%s", (u["id"],))
            db.execute("delete from users where id=%s", (u["id"],))


@pytest.mark.parametrize("disconnect", [False, True])
def test_player_sse_save_and_disconnect_share_atomic_settlement(player, monkeypatch, disconnect):
    """Exercise orchestration with an isolated provider stand-in, independently of live acceptance."""
    import asyncio

    from starlette.responses import StreamingResponse

    from platform_app import branches
    from platform_app.api.player import Execute, event, execute
    from platform_app.player.meter import current

    monkeypatch.setattr("platform_app.branches.runtime.schedule_llm_summary", lambda *a: None)

    async def opening(api_user):
        async def chunks():
            run = current(api_user["id"])
            run.record(
                str(uuid.uuid4()), "openai", "test", {"prompt_tokens": 100, "completion_tokens": 50}
            )
            yield event("token", {"text": "有效的开场正文。"})
            if disconnect:
                await asyncio.Event().wait()  # Model is still generating at disconnect.
            else:
                save = catalog.player_save(player["uid"], player["sid"])
                run.committing = True
                branches.record_runtime_turn(
                    "", "有效的开场正文。", user_id=player["uid"], state_data=save["state_snapshot"]
                )

        return StreamingResponse(chunks())

    monkeypatch.setattr("routes.game.opening.api_opening", opening)
    save = catalog.player_save(player["uid"], player["sid"])
    q = wallet.make_quote(player["uid"], save, player["profile"], "opening", "", 200)
    rid = uuid.uuid4()
    body = Execute(
        save_id=player["sid"],
        kind="opening",
        message="",
        quote_id=q["id"],
        request_id=rid,
        action_id=str(uuid.uuid4()),
    )

    async def run_stream():
        response = await execute(body, player["user"])
        stream = response.body_iterator
        first = await anext(stream)
        assert "saving" in first
        second = await anext(stream)
        assert "有效的开场正文" in second
        if disconnect:
            with pytest.raises(asyncio.CancelledError):
                await stream.athrow(asyncio.CancelledError())
        else:
            frames = [frame async for frame in stream]
            assert any("event: receipt" in frame for frame in frames)

    asyncio.run(run_stream())
    with connect() as db:
        req = db.execute("select * from player_requests where id=%s", (rid,)).fetchone()
    assert req["status"] == "settled" and req["charged_micro"] == 300000
    assert req["receipt"]["partial"] == disconnect
    assert wallet.wallet(player["uid"])["held_micro"] == 0
    assert catalog.view(player["uid"], player["sid"])["has_opening"]


def test_unlisted_can_continue_but_suspended_blocks_generation(player):
    with connect() as db:
        db.execute("update player_stories set status='unlisted' where id=%s", (player["story"],))
    assert catalog.story(player["story"])
    with pytest.raises(HTTPException):
        catalog.story(player["story"], new=True)
    req, _, _ = reservation(player)
    run = Run(req)
    with connect() as db:
        db.execute("update player_stories set status='suspended' where id=%s", (player["story"],))
    with pytest.raises(HTTPException) as e:
        run.admit("action", 100)
    assert e.value.status_code == 503
    assert catalog.view(player["uid"], player["sid"])
    wallet.release(player["uid"], str(req["id"]))


@pytest.mark.parametrize("empty", [False, True])
def test_managed_opening_missing_model_ops_or_empty_reply_has_safe_commit(player, monkeypatch, empty):
    import asyncio
    from types import SimpleNamespace

    from platform_app.api.player import Execute, execute
    from platform_app.player.character_creation import prepare
    from state import GameState

    save = catalog.player_save(player["uid"], player["sid"])
    data = copy.deepcopy(save["state_snapshot"])
    setup = prepare(
        {"character_creation": {"martial_soul": {"enabled": True, "choices": [{"name": "铁剑"}]}}},
        {"mode": "recommended", "name": "铁剑"},
    )
    data["player_setup"] = setup
    with connect() as db:
        db.execute("update game_saves set state_snapshot=%s where id=%s", (Jsonb(data), player["sid"]))
        db.execute("update branch_commits set state_snapshot=%s where id=%s", (Jsonb(data), save["active_commit_id"]))
    state = GameState(copy.deepcopy(data))
    gm = SimpleNamespace(
        api_id="test",
        generate_opening_stream=lambda *a, **k: iter([] if empty else ["你走出会堂，与村长商量求学道路。"]),
    )
    monkeypatch.setattr(app, "_ensure_loaded", lambda *a, **k: state)
    monkeypatch.setattr(app, "_get_gm", lambda *a, **k: gm)
    monkeypatch.setattr(app, "_active_script_id", lambda *a: None)
    monkeypatch.setattr(app, "retrieve_context", lambda *a, **k: {})
    monkeypatch.setattr(app, "_build_turn_context", lambda *a, **k: {"prompt": ""})
    monkeypatch.setattr(app, "_payload_sse", lambda *a: {})
    monkeypatch.setattr("platform_app.branches.runtime.schedule_llm_summary", lambda *a: None)
    save = catalog.player_save(player["uid"], player["sid"])
    quote = wallet.make_quote(player["uid"], save, player["profile"], "opening", "", 200)
    rid = uuid.uuid4()
    body = Execute(save_id=player["sid"], kind="opening", message="", quote_id=quote["id"], request_id=rid, action_id=str(uuid.uuid4()))

    async def consume():
        response = await execute(body, player["user"])
        return [frame async for frame in response.body_iterator]

    frames = asyncio.run(consume())
    dto = catalog.view(player["uid"], player["sid"])
    with connect() as db:
        req = db.execute("select status,charged_micro from player_requests where id=%s", (rid,)).fetchone()
    assert wallet.wallet(player["uid"])["held_micro"] == 0
    if empty:
        assert req["status"] == "released" and not req["charged_micro"]
        assert not dto["has_opening"] and not dto["character_setup"]["completed"]
    else:
        assert req["status"] == "settled" and dto["character_setup"]["completed"]
        assert "武魂觉醒与先天魂力测定已经完成" in dto["messages"][-1]["text"]
        assert any("event: receipt" in frame for frame in frames)
        assert len(dto["options"]) == 4
