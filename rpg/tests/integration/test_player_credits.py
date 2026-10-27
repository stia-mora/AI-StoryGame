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


def test_guide_future_permission_is_bound_to_quote_and_replay(player):
    uid, sid = player["uid"], player["sid"]
    save = catalog.player_save(uid, sid)
    question = "战局今后如何？"
    quote = wallet.make_quote(uid, save, player["profile"], "guide", question, 200,
                              reveal_future=True)
    rid = str(uuid.uuid4())
    with pytest.raises(HTTPException) as mismatch:
        wallet.reserve(uid, save, quote["id"], rid, "future-guide", "guide", question)
    assert mismatch.value.status_code == 409
    req, replay = wallet.reserve(uid, save, quote["id"], rid, "future-guide", "guide", question,
                                 reveal_future=True)
    assert not replay and req["profile"]["guide_options"]["reveal_future"] is True
    with pytest.raises(HTTPException) as changed_replay:
        wallet.reserve(uid, save, quote["id"], rid, "future-guide", "guide", question)
    assert changed_replay.value.status_code == 409
    wallet.release(uid, rid, "test complete")
    ordinary = wallet.make_quote(uid, save, player["profile"], "guide", question, 200)
    req, _ = wallet.reserve(uid, save, ordinary["id"], str(uuid.uuid4()), "ordinary-guide",
                            "guide", question)
    assert req["profile"]["guide_options"]["reveal_future"] is False
    wallet.release(uid, str(req["id"]), "test complete")


def test_guide_rejects_changed_world_version_before_settlement(player):
    from platform_app.player import guide, guide_world

    uid, sid = player["uid"], player["sid"]
    save = catalog.player_save(uid, sid)
    model = {"version": 1, "edition": "v1", "moments": [
        {"key": "start", "order": 0, "label": "开篇", "chapter_min": 1, "chapter_max": 1},
    ], "subjects": [], "facts": []}
    quote = wallet.make_quote(uid, save, player["profile"], "guide", "局势？", 200)
    req, _ = wallet.reserve(uid, save, quote["id"], str(uuid.uuid4()), "version-guide",
                            "guide", "局势？")
    run = Run(req)
    run.guide_script_id = save["script_id"]
    run.guide_version = guide_world.knowledge_version(model)
    changed = {**model, "edition": "v2"}
    with connect() as db:
        db.execute("insert into script_overrides(script_id,data) values(%s,%s)",
                   (save["script_id"], Jsonb({"guide_world": changed})))
    with pytest.raises(HTTPException) as invalid:
        guide.commit(run, "局势？", "旧版本的回答", [])
    assert invalid.value.status_code == 409
    with connect() as db:
        request = db.execute("select status from player_requests where id=%s", (run.id,)).fetchone()
        current = db.execute("select active_commit_id,state_snapshot from game_saves where id=%s",
                             (sid,)).fetchone()
    assert request["status"] == "reserved"
    assert current["active_commit_id"] == save["active_commit_id"]
    assert current["state_snapshot"] == save["state_snapshot"]
    wallet.release(uid, run.id, "test complete")


def test_guide_world_checks_ownership_and_uses_bound_script(player):
    from platform_app.player import guide_world

    uid, sid = player["uid"], player["sid"]
    save = catalog.player_save(uid, sid)
    model = {"version": 1, "edition": "bound-script", "moments": [
        {"key": "start", "order": 0, "label": "开篇", "chapter_min": 1, "chapter_max": 1},
    ], "subjects": [], "facts": []}
    with connect() as db:
        db.execute("insert into script_overrides(script_id,data) values(%s,%s)",
                   (save["script_id"], Jsonb({"guide_world": model})))
    assert guide_world.load(uid, sid).model.edition == "bound-script"
    with pytest.raises(HTTPException) as denied:
        guide_world.load(-1, sid, allow_future=True)
    assert denied.value.status_code == 404


def test_guide_consultations_follow_active_branch_ancestry(player):
    from platform_app.branches.commits import _insert_commit
    from platform_app.player import guide

    uid, sid = player["uid"], player["sid"]
    root = catalog.player_save(uid, sid)

    def consult(text):
        save = catalog.player_save(uid, sid)
        quote = wallet.make_quote(uid, save, player["profile"], "guide", text, 200)
        req, _ = wallet.reserve(uid, save, quote["id"], str(uuid.uuid4()), text, "guide", text)
        guide.commit(Run(req), text, text, [])

    consult("共同祖先的咨询")
    with connect() as db:
        siblings = [_insert_commit(
            db, save_id=sid, parent_id=root["active_commit_id"], turn_index=1,
            kind="turn", title=label, message="", summary="", content_preview="",
            state_path="", state_snapshot=root["state_snapshot"],
        )["id"] for label in ("左支", "右支")]
    for branch, text in zip(siblings, ("左支的咨询", "右支的咨询")):
        with connect() as db:
            db.execute("update game_saves set active_commit_id=%s where id=%s", (branch, sid))
        consult(text)
    assert [r["text"] for r in guide.history(uid, sid)] == ["共同祖先的咨询", "右支的咨询"]
    with connect() as db:
        db.execute("update game_saves set active_commit_id=%s where id=%s", (siblings[0], sid))
    assert [r["text"] for r in guide.history(uid, sid)] == ["共同祖先的咨询", "左支的咨询"]


@pytest.mark.parametrize('coarse', [False, True])
def test_recorded_rescue_commits_and_branch_checkout_restores_its_own_world(player, monkeypatch, coarse):
    import json
    from types import SimpleNamespace

    from agents import recorder
    from chat_pipeline.postproc import _apply_gm_json_ops, _response_with_recorder_ops
    from platform_app import branches
    from platform_app.branches import runtime as branch_runtime
    from platform_app.player import guide_world
    from state import GameState

    uid, sid = player["uid"], player["sid"]
    root = catalog.player_save(uid, sid)
    baseline = copy.deepcopy(root["state_snapshot"])
    baseline["world"].update(guide_edition="rescue-test", time="战后")
    baseline["worldline"]["progress_chapter"] = 12
    model = {"version": 1, "edition": "rescue-test", "continuity_policy": "causal", "moments": [
        {"key": "battle", "order": 1, "label": "战后", "chapter_min": 12, "chapter_max": 12},
        {"key": "next", "order": 2, "label": "翌日", "chapter_min": 13, "chapter_max": 13},
    ], "subjects": [{"key": "hou", "name": "侯丹", "kind": "character"}], "facts": [
        {"id": "death", "subject": "hou", "kind": "state", "field": "status", "value": "原著阵亡",
         "starts_at": "battle", "basis": "novel", "evidence": [{"source": "测试", "locator": "12章"}]},
    ], "beats": [dict(key='casualty-review', title='战后伤亡核验', starts_at='battle', ends_at='next',
                      subjects=['hou'], pressure='核当前分支的实际伤亡与救护。',
                      conditions=[dict(key='health', label='人员状态', fact_ids=['death'],
                                       recheck='若本分支已救下，按实际伤势安排后续。')],
                      choices=['可按实际伤情安排照护。'],
                      evidence=[dict(source='测试故事', locator='12章')]) ]}
    guide_world.bind_initial(model, baseline)
    with connect() as db:
        db.execute("insert into script_overrides(script_id,data) values(%s,%s)",
                   (root["script_id"], Jsonb({"guide_world": model})))
        db.execute("update branch_commits set state_snapshot=%s where id=%s",
                   (Jsonb(baseline), root["active_commit_id"]))
        db.execute("update game_saves set state_snapshot=%s where id=%s", (Jsonb(baseline), sid))
    branches.activate_save(uid, sid)
    from agents.anchor_seed_agent import seed_anchors_for_save
    from platform_app.knowledge import ensure_game_session

    session = ensure_game_session(uid, sid, baseline)
    with connect() as db:
        events = [dict(event="侯丹救护未及而阵亡", participants=["侯丹"], importance="high"),
                  dict(event="宋廷继续转运军粮至前线", importance="high")]
        db.execute("insert into chapter_facts(book_id,script_id,chapter,events) values(%s,%s,12,%s)",
                   (session["book_id"], root["script_id"], Jsonb(events)))
        if coarse:
            db.execute("insert into script_worldlines(script_id,wl_key,label,is_primary) values(%s,'main','主线',true)",
                       (root["script_id"],))
            db.execute("insert into script_worldline_nodes(script_id,wl_key,node_key,seq,label,summary,"
                       "chapter_min,chapter_max,anchor_keys,must_preserve) "
                       "values(%s,'main','hou',1,'战场救援','侯丹救护未及而阵亡',12,12,%s,%s)",
                       (root["script_id"], Jsonb(["chapter:12:event:0"]), Jsonb(["侯丹阵亡"])))
        db.execute("update game_sessions set worldline=worldline || %s where save_id=%s",
                   (Jsonb(dict(steering_strength="rail", progress_chapter=12)), sid))
    assert seed_anchors_for_save(sid)["seeded"] == 2
    with connect() as db:
        seeded = db.execute("select is_fatal,must_preserve,metadata from save_anchor_states "
                            "where save_id=%s and anchor_key='chapter:12:event:0'", (sid,)).fetchone()
    assert not seeded["is_fatal"] and not seeded["must_preserve"]
    assert seeded["metadata"]["original_is_fatal"]
    before_wish = copy.deepcopy(catalog.player_save(uid, sid)["state_snapshot"])
    guide_world.load(uid, sid).query(dict(tool="get_character", query="侯丹"))
    assert catalog.player_save(uid, sid)["state_snapshot"] == before_wish
    prose = "你将侯丹拖离战阵。军医确认侯丹尚活，右臂受伤，留营休养。"
    op = {"op": "world_fact", "subject": "侯丹", "field": "status", "value": "存活，右臂受伤",
          "quote": "军医确认侯丹尚活，右臂受伤，留营休养。", "cause": "玩家拖离战阵", "diverges": True}
    monkeypatch.setattr(recorder, "_resolve_recorder_api_and_model", lambda *a: ("test", "test"))
    monkeypatch.setattr(recorder, "_call_recorder", lambda **kw: (json.dumps({"ops": [op]}), {}))
    monkeypatch.setattr(branch_runtime, "schedule_llm_summary", lambda *a: None)
    g = GameState(copy.deepcopy(baseline))
    g.data["turn"] = 1
    g.data["permissions"]["mode"] = "full_access"
    extracted = recorder.record_turn(prose, g.data, tasks=["ops"], user_id=uid)
    updates = _apply_gm_json_ops(
        state=g, response_with_ops=_response_with_recorder_ops(prose, extracted["ops"]),
        api_user=player["user"], active_script_id=lambda _: root["script_id"],
        ctx=SimpleNamespace(early_active_save_id=sid, directive_updates=[]),
    )
    assert any("世界事实" in u for u in updates)
    request, _, _ = reservation(player, "救人")
    run = Run(request)
    run.committing = True
    token = active_run.set(run)
    try:
        with phase("reply"):
            run.record(str(uuid.uuid4()), "openai", "text", {"prompt_tokens": 100, "completion_tokens": 50})
        committed = branches.record_runtime_turn("救人", prose, user_id=uid, state_data=g.data)
    finally:
        active_run.reset(token)
    assert committed["ok"]
    rescued_id = catalog.player_save(uid, sid)["active_commit_id"]
    from kb.save_kb import materialize
    with connect() as db:
        projected = materialize(db, sid, rescued_id)
    assert projected["world_facts"] == g.data["world_facts"]
    result = guide_world.load(uid, sid).query({"tool": "get_character", "query": "侯丹"})
    assert result["facts"][0]["value"] == "存活，右臂受伤"
    assert result["facts"][0]["basis"] == "save"
    assert result["as_of"]["divergence_chapter"] == 12
    assert run.receipt["charged_micro"] == 300_000

    def gm_reference():
        from agents.gm import master
        from context_engine import build_context_bundle
        from context_providers import Demand, ProviderServices, resolve_content_pack, run_providers
        from gm_serving.serve import assemble_gm_context
        from retrieval import assemble

        current = catalog.player_save(uid, sid)
        state = GameState(copy.deepcopy(current["state_snapshot"]))
        manifest = resolve_content_pack(state, script_id=root["script_id"])
        manifest["context_providers"] = ["curated_world", "novel_characters"]
        contributions, used = run_providers(
            state, manifest, Demand(player_intent="询问侯丹伤势"),
            ProviderServices(user_id=uid, script_id=root["script_id"], save_id=sid),
        )
        assert used == ["curated_world", "novel_characters"]
        npc_reference = next(layer["content"] for layer in contributions[1].layers if layer["id"] == "npc_cards")
        current_status = guide_world.load(uid, sid).query({"tool": "get_character", "query": "侯丹"})["facts"][0]["value"]
        assert current_status in npc_reference
        conditions = guide_world.load(uid, sid).query(dict(tool='get_scene_conditions'))['facts']
        expected = 'reassess' if current_status == '存活，右臂受伤' else 'baseline'
        assert conditions[0]['conditions'][0]['state'] == expected
        scene_layer = next(layer for layer in contributions[0].layers if layer['id'] == 'scene_conditions')
        assert current_status in scene_layer['content'] and expected in scene_layer['content']
        bundle = build_context_bundle(state, "询问侯丹伤势", contributions=contributions, manifest=manifest)
        with connect() as db:
            serving = assemble_gm_context(db, save_id=sid, user_id=uid, state=state)
            stored = assemble_gm_context(db, save_id=sid, user_id=uid)
        assert serving["steering"]["strength"] == stored["steering"]["strength"] == "causal"
        assert '侯丹救护未及而阵亡' in serving["injection_text"]
        assert '强制下一拍' not in serving["injection_text"]
        monkeypatch.setattr(assemble, '_ensure_timeline_ready', lambda: None)
        retrieved = assemble.retrieve_context('我想救侯丹，问宋廷粮运', state=state, user_id=uid,
                                              script_id=root['script_id'])
        assert '宋廷继续转运军粮至前线' in retrieved  # A local rescue does not disable unrelated baseline.
        assert '原著候选事件' in retrieved and '结果不可省' not in retrieved
        assert '死神来了·必发生' not in retrieved and '1-3 轮内' not in retrieved
        gm = master.GameMaster.__new__(master.GameMaster)
        gm._active_state, gm.user_id = state, uid
        monkeypatch.setattr(gm, '_world_section_for_active_content', lambda: '')
        final_prompt = gm._build_system(style_profile={}) + serving['injection_text'] + retrieved + bundle['prompt']
        assert current_status in final_prompt and '因果改史' in final_prompt
        assert '玩家任何阻止尝试都会' not in final_prompt
        reference = []
        for contribution in contributions:
            for layer in contribution.layers:
                assert layer["content"] in bundle["prompt"]
                if layer['id'] != 'scene_conditions':  # Baseline comparisons are explicit inside conditions.
                    reference.append(layer["content"])
        return "\n".join(reference)

    reference = gm_reference()
    assert "存活，右臂受伤" in reference and "原著阵亡" not in reference
    branches.activate_node(uid, root["active_commit_id"])
    result = guide_world.load(uid, sid).query({"tool": "get_character", "query": "侯丹"})
    assert result["facts"][0]["value"] == "原著阵亡"
    assert result["as_of"]["divergence_turn"] is None
    assert "原著阵亡" in gm_reference()
    branches.activate_node(uid, rescued_id)
    assert guide_world.load(uid, sid).query({"tool": "get_character", "query": "侯丹"})["facts"][0]["value"] == "存活，右臂受伤"
    reference = gm_reference()
    assert "存活，右臂受伤" in reference and "原著阵亡" not in reference


@pytest.mark.parametrize("chapter,expected", [(None, "start"), (12, "battle"), (999, None)])
def test_free_character_creation_binds_guide_world_before_root_and_kb_seed(player, chapter, expected):
    from kb.save_kb import materialize
    from platform_app.api.player import Create, create
    from platform_app.knowledge import ensure_game_session
    from platform_app.player import guide_world

    uid, sid = player["uid"], player["sid"]
    script_id = catalog.player_save(uid, sid)["script_id"]
    model = {"version": 1, "edition": "creation-test", "continuity_policy": "causal", "moments": [
        {"key": "historical", "order": 0, "label": "早期史实参考"},
        {"key": "start", "order": 1, "label": "开篇", "chapter_min": 1, "chapter_max": 2},
        {"key": "battle", "order": 10, "label": "会战", "chapter_min": 12, "chapter_max": 12},
    ], "subjects": [], "facts": []}
    defaults = {"birthpoint": {"chapter_min": chapter, "chapter_max": chapter}} if chapter else {}
    original = catalog.player_save(uid, sid)
    source = ensure_game_session(uid, sid, original['state_snapshot'])
    with connect() as db:
        db.execute("insert into script_overrides(script_id,data) values(%s,%s)",
                   (script_id, Jsonb({"guide_world": model})))
        db.execute("update player_stories set identities=%s,defaults=%s where id=%s",
                   (Jsonb([{"id": "native", "name": "随行小吏"}]), Jsonb(defaults), player["story"]))
        db.execute('insert into chapter_facts(book_id,script_id,chapter,events) values(%s,%s,12,%s)',
                   (source['book_id'], script_id, Jsonb([
                       dict(event='侯丹战死沙场，军士收殓', importance='high')
                   ])))
    view = create(Create(story_id=player["story"], name="新角色", identity_id="native"), user=player["user"])
    saved = catalog.player_save(uid, view["save"]["id"])
    assert saved["state_snapshot"]["world"]["guide_edition"] == "creation-test"
    assert saved["state_snapshot"]["world"]["guide_policy"] == "causal"
    assert saved["state_snapshot"]["world"].get("guide_moment") == expected
    with connect() as db:
        root = db.execute("select state_snapshot from branch_commits where id=%s", (saved["active_commit_id"],)).fetchone()
        kb = materialize(db, saved["id"], saved["active_commit_id"])
        seeded = db.execute('select is_fatal,metadata from save_anchor_states where save_id=%s',
                            (saved['id'],)).fetchall()
    assert len(seeded) == 1 and not seeded[0]['is_fatal']
    assert seeded[0]['metadata']['original_is_fatal']
    assert root["state_snapshot"]["world"]["guide_edition"] == kb["world"]["guide_edition"] == "creation-test"
    assert guide_world.load(uid, saved["id"]).clock()["moment_key"] == expected
    assert wallet.wallet(uid)["held_micro"] == 0
    assert wallet.wallet(uid)["free_micro"] == 100_000_000


@pytest.mark.parametrize('causal', [False, True])
def test_anchor_seeding_keeps_legacy_fatal_contract_and_causal_reference(player, causal):
    from agents.anchor_seed_agent import seed_anchors_for_save
    from platform_app.knowledge import ensure_game_session

    uid, sid = player['uid'], player['sid']
    saved = catalog.player_save(uid, sid)
    snapshot = copy.deepcopy(saved['state_snapshot'])
    if causal:
        snapshot['world'].update(guide_edition='seed-test', guide_policy='causal')
    session = ensure_game_session(uid, sid, snapshot)
    with connect() as db:
        db.execute('update game_saves set state_snapshot=%s where id=%s', (Jsonb(snapshot), sid))
        event = dict(event='侯丹战死沙场，军士收殓', participants=['侯丹'], importance='high')
        db.execute('insert into chapter_facts(book_id,script_id,chapter,events) values(%s,%s,1,%s)',
                   (session['book_id'], saved['script_id'], Jsonb([event])))
    assert seed_anchors_for_save(sid)['seeded'] == 1
    with connect() as db:
        row = db.execute('select is_fatal,must_preserve,metadata from save_anchor_states where save_id=%s',
                         (sid,)).fetchone()
    assert row['is_fatal'] is (not causal)
    assert bool(row['must_preserve']) is (not causal)
    if causal:
        assert row['metadata']['original_is_fatal'] and row['metadata']['original_outcomes']
    else:
        assert 'continuity_policy' not in row['metadata']


def test_invalid_guide_data_prevents_half_created_save_without_charging(player):
    from platform_app.api.player import Create, create

    uid = player["uid"]
    script_id = catalog.player_save(uid, player["sid"])["script_id"]
    with connect() as db:
        db.execute("insert into script_overrides(script_id,data) values(%s,%s)",
                   (script_id, Jsonb({"guide_world": {"version": 1, "edition": "broken", "moments": []}})))
        db.execute("update player_stories set identities=%s where id=%s",
                   (Jsonb([{"id": "native", "name": "随行小吏"}]), player["story"]))
        before = db.execute("select count(*) as n from game_saves where user_id=%s", (uid,)).fetchone()["n"]
    with pytest.raises(HTTPException) as invalid:
        create(Create(story_id=player["story"], name="新角色", identity_id="native"), user=player["user"])
    assert invalid.value.status_code == 503
    with connect() as db:
        after = db.execute("select count(*) as n from game_saves where user_id=%s", (uid,)).fetchone()["n"]
    assert before == after
    assert wallet.wallet(uid)["held_micro"] == 0


@pytest.mark.parametrize("new_time,expected", [
    ("同章午后", "afternoon"),
    ("次章清晨", "morning"),
    ("尚未编定的日期", "start"),
])
def test_narrated_time_reaches_guide_gm_and_npc_cards_after_paid_commit(player, monkeypatch, new_time, expected):
    import json
    from types import SimpleNamespace

    from agents import recorder
    from chat_pipeline.postproc import _apply_gm_json_ops, _response_with_recorder_ops
    from context_engine import build_context_bundle
    from context_providers import Demand, ProviderServices, resolve_content_pack, run_providers
    from gm_serving.recorder_bridge import run_unified_recorder
    from kb.save_kb import materialize
    from platform_app import branches
    from platform_app.api.player import Create, create
    from platform_app.branches import runtime as branch_runtime
    from platform_app.player import guide_world
    from state import GameState

    uid = player["uid"]
    script_id = catalog.player_save(uid, player["sid"])["script_id"]
    stages = [("start", "同章清晨", 1), ("afternoon", "同章午后", 1),
              ("morning", "次章清晨", 2), ("evening", "次章入夜", 2)]
    model = dict(version=1, edition="narrated-clock", moments=[
        dict(key=key, order=index, label=label, chapter_min=chapter, chapter_max=chapter)
        for index, (key, label, chapter) in enumerate(stages)
    ], subjects=[dict(key="clerk", name="随军书吏", kind="character")], facts=[
        dict(id=f"{key}-{field}", subject="clerk", kind="state", field=field,
             value=f"{key}期的{field}", starts_at=key,
             ends_at=stages[index+1][0] if index+1 < len(stages) else None,
             basis="novel", evidence=[dict(source="测试故事", locator=label)])
        for index, (key, label, _) in enumerate(stages)
        for field in ("status", "personality", "speech_style")
    ])
    with connect() as db:
        db.execute("insert into script_overrides(script_id,data) values(%s,%s)",
                   (script_id, Jsonb({"guide_world": model})))
        db.execute("update player_stories set identities=%s where id=%s",
                   (Jsonb([{"id": "native", "name": "随行小吏"}]), player["story"]))
    view = create(Create(story_id=player["story"], name="玩家", identity_id="native"), user=player["user"])
    sid = view["save"]["id"]
    branches.activate_save(uid, sid)
    original = catalog.player_save(uid, sid)
    assert guide_world.load(uid, sid).clock()["moment_key"] == "start"
    g = GameState(copy.deepcopy(original["state_snapshot"]))
    prose = f"时间到了{new_time}，随军书吏前来听命。"
    op = dict(op="set", path="world.time", value=new_time)
    monkeypatch.setattr(recorder, "_resolve_recorder_api_and_model", lambda *a: ("test", "test"))
    monkeypatch.setattr(recorder, "_call_recorder", lambda **kw: (json.dumps({"ops": [op]}), {}))
    monkeypatch.setattr(branch_runtime, "schedule_llm_summary", lambda *a: None)
    extracted = run_unified_recorder(g, prose, sid, uid, tasks=["ops"])
    _apply_gm_json_ops(
        state=g, response_with_ops=_response_with_recorder_ops(prose, extracted["ops"]),
        api_user=player["user"], active_script_id=lambda _: script_id,
        ctx=SimpleNamespace(early_active_save_id=sid, directive_updates=[]),
    )
    assert g.data["world"]["time"] == new_time
    assert "guide_moment" not in g.data["world"]
    request, _, _ = reservation({**player, "sid": sid}, "等候书吏")
    run = Run(request)
    token = active_run.set(run)
    try:
        with phase("reply"):
            run.record(str(uuid.uuid4()), "openai", "text", {"prompt_tokens": 100, "completion_tokens": 50})
        app._persist_chat_turn(player["user"], g, "等候书吏", prose,
                               persist_user_id=uid, active_save_id=sid)
    finally:
        active_run.reset(token)
    advanced = catalog.player_save(uid, sid)
    assert advanced["active_commit_id"] != original["active_commit_id"]
    assert run.receipt["charged_micro"] == 300_000
    with connect() as db:
        projected = materialize(db, sid, advanced["active_commit_id"])
    assert projected["world"] == advanced["state_snapshot"]["world"]

    def check_current(moment):
        snapshot = catalog.player_save(uid, sid)["state_snapshot"]
        before = copy.deepcopy(snapshot)
        query = guide_world.load(uid, sid)
        assert query.clock()["moment_key"] == moment
        rows = query.query(dict(tool="get_character", query="随军书吏"))["facts"]
        assert {row["value"] for row in rows} == {
            f"{moment}期的{field}" for field in ("status", "personality", "speech_style")}
        state = GameState(copy.deepcopy(snapshot))
        manifest = resolve_content_pack(state, script_id=script_id)
        manifest["context_providers"] = ["curated_world", "novel_characters"]
        contributions, used = run_providers(
            state, manifest, Demand(player_intent="随军书吏如何奏对"),
            ProviderServices(user_id=uid, script_id=script_id, save_id=sid))
        assert used == ["curated_world", "novel_characters"]
        assert all(c.debug["moment"] == moment for c in contributions)
        bundle = build_context_bundle(state, "随军书吏如何奏对", contributions=contributions, manifest=manifest)
        for contribution in contributions:
            text = "\n".join(layer["content"] for layer in contribution.layers)
            assert f"{moment}期的personality" in text and f"{moment}期的speech_style" in text
            assert "evening期的" not in text
            for layer in contribution.layers:
                assert layer["content"] in bundle["prompt"]
        # Even an explicitly authorised future lookup is read-only.
        future = guide_world.load(uid, sid, allow_future=True)
        assert future.query(dict(tool="get_character", query="随军书吏", at="evening"))["facts"]
        assert catalog.player_save(uid, sid)["state_snapshot"] == before
        assert state.data == before

    check_current(expected)
    branches.activate_node(uid, original["active_commit_id"])
    check_current("start")
    branches.activate_node(uid, advanced["active_commit_id"])
    check_current(expected)


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


def test_expired_reservations_are_released_in_bounded_batches(player, monkeypatch):
    monkeypatch.setattr(wallet, "REAP_BATCH_SIZE", 2)
    users, requests = [], []
    with connect() as db:
        script = db.execute("select script_id from game_saves where id=%s", (player["sid"],)).fetchone()["script_id"]
        for index in range(3):
            uid = db.execute("insert into users(username,password_hash,display_name) values(%s,'test','Batch') returning id",
                             ("reap_" + uuid.uuid4().hex,)).fetchone()["id"]
            users.append(uid)
            save = db.execute("insert into game_saves(user_id,script_id,title,state_path,state_snapshot) "
                              "values(%s,%s,'Batch','',%s) returning id", (uid, script, Jsonb({}))).fetchone()["id"]
            db.execute("insert into player_wallets(user_id,free_day,free_micro,held_micro) "
                       "values(%s,(now() at time zone 'Asia/Shanghai')::date,0,10)", (uid,))
            qid, rid = uuid.uuid4(), uuid.uuid4()
            requests.append(rid)
            db.execute("insert into player_quotes(id,user_id,save_id,kind,message_hash,profile,rates,estimate_micro,cap_micro) "
                       "values(%s,%s,%s,'turn','test',%s,%s,1,10)", (qid, uid, save, Jsonb({}), Jsonb({})))
            db.execute("insert into player_requests(id,user_id,save_id,quote_id,action_id,kind,free_day,free_hold,"
                       "permanent_hold,cap_micro,rates,profile,expires_at) values(%s,%s,%s,%s,'action','turn',"
                       "(now() at time zone 'Asia/Shanghai')::date,10,0,10,%s,%s,"
                       "'1900-01-01'::timestamptz + %s * interval '1 second')",
                       (rid, uid, save, qid, Jsonb({}), Jsonb({}), index))
    try:
        wallet.reap()
        with connect() as db:
            rows = db.execute("select id,status from player_requests where id=any(%s)", (requests,)).fetchall()
            states = {row["id"]: row["status"] for row in rows}
            assert [states[rid] for rid in requests] == ["released", "released", "reserved"]
        wallet.reap()
        with connect() as db:
            rows = db.execute("select free_micro,held_micro from player_wallets where user_id=any(%s)", (users,)).fetchall()
            assert len(rows) == 3 and all(row["free_micro"] == 10 and row["held_micro"] == 0 for row in rows)
    finally:
        with connect() as db:
            db.execute("delete from player_ledger where user_id=any(%s)", (users,))
            db.execute("delete from player_requests where user_id=any(%s)", (users,))
            db.execute("delete from player_quotes where user_id=any(%s)", (users,))
            db.execute("delete from game_saves where user_id=any(%s)", (users,))
            db.execute("delete from player_wallets where user_id=any(%s)", (users,))
            db.execute("delete from users where id=any(%s)", (users,))


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


@pytest.mark.parametrize('custom', [False, True])
def test_original_character_keeps_canonical_name_and_own_start(player, custom):
    from platform_app.api.player import Create, create

    identities = [{'id': 'yue', 'name': '岳飞', 'character_name': '岳飞',
                   'role': '独立领军的将领', 'background': '初次自领一军。',
                   'birthpoint': {'story_time_label': '领军之初', 'chapter_min': 10, 'chapter_max': 10}}]
    with connect() as db:
        db.execute('update player_stories set identities=%s,defaults=%s where id=%s',
                   (Jsonb(identities), Jsonb({'birthpoint': {'story_time_label': '明道宫',
                    'chapter_min': 1, 'chapter_max': 1}}), player['story']))
    public = catalog.public_story(catalog.story(player['story']))
    assert public['identities'][0]['character_name'] == '岳飞'
    assert 'birthpoint' not in public['identities'][0]
    view = create(Create(story_id=player['story'], name='自定姓名', identity_id='yue',
                         custom_identity='军中书吏' if custom else ''), user=player['user'])
    save = catalog.player_save(player['uid'], view['save']['id'])
    assert view['status']['name'] == ('自定姓名' if custom else '岳飞')
    assert view['status']['time'] == ('明道宫' if custom else '领军之初')
    assert not view['has_opening']
    with connect() as db:
        root = db.execute('select state_snapshot from branch_commits where save_id=%s order by id limit 1',
                          (save['id'],)).fetchone()['state_snapshot']
        assert root['player']['name'] == view['status']['name']
        assert not db.execute('select id from player_requests where save_id=%s', (save['id'],)).fetchall()


def test_longer_narration_quote_covers_gm_and_curator_output(player):
    from platform_app.api.player import estimate_usage

    profile = {**player['profile'], 'max_output': 6144}
    save = catalog.player_save(player['uid'], player['sid'])
    assert estimate_usage(player['uid'], save, profile, 'opening', '')[1] == 6144
    assert estimate_usage(player['uid'], save, profile, 'turn', '核对名籍并交付结果')[1] == 7944


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
