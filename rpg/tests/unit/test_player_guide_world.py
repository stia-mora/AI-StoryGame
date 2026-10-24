import copy
import json

import pytest
from pydantic import ValidationError

from platform_app.player.guide_world import GuideWorld, WorldQueries


@pytest.fixture
def world():
    moments = [dict(key=key, order=order, label=label, chapter_min=lo, chapter_max=hi)
               for key, order, label, lo, hi in [
                   ("early", 0, "建炎初年", 1, 10),
                   ("battle", 10, "尧山决战", 11, 12),
                   ("after", 20, "尧山战后", 13, 20),
               ]]
    subjects = [dict(key=key, name=name, kind=kind) for key, name, kind in [
        ("wu", "吴玠", "character"), ("hou", "侯丹", "character"),
        ("yao", "尧山", "place"), ("song", "宋廷", "world"),
    ]]
    def fact(key, subject, field, value, starts="early", ends=None,
             basis="novel", kind="state"):
        return dict(id=key, subject=subject, field=field, value=value,
                    starts_at=starts, ends_at=ends, basis=basis, kind=kind,
                    evidence=[{"source": "原著" if basis == "novel" else "史籍",
                               "locator": "第14章后揭已发生的事"}])
    return dict(version=1, edition="test-v1", moments=moments, subjects=subjects, facts=[
        fact("wu-early", "wu", "identity", "经略使", ends="after"),
        fact("wu-late", "wu", "identity", "战后领军", starts="after"),
        fact("wu-history", "wu", "identity", "真实历史不同官职", basis="history"),
        fact("hou-alive", "hou", "status", "存活", ends="battle"),
        fact("hou-dead", "hou", "status", "阵亡", starts="battle"),
        fact("place", "yao", "situation", "战前集军", ends="battle"),
        fact("place-after", "yao", "situation", "战后收束", starts="after"),
        fact("event-early", "song", "event", "整军", kind="event"),
        fact("event-battle", "song", "event", "决战", starts="battle", kind="event"),
        fact("event-after", "song", "event", "军改", starts="after", kind="event"),
        fact("history-after", "song", "event", "史籍对照后事", starts="after",
             basis="history", kind="history"),
    ])


def engine(world, chapter=11, future=False, state=None):
    return WorldQueries(world, state or {"worldline": {"progress_chapter": chapter}},
                        script_id=3, save_id=9, allow_future=future)


def values(result):
    return [f["value"] for f in result["facts"]]


def test_character_uses_period_and_novel_before_history(world):
    assert values(engine(world).query({"tool": "get_character", "query": "吴玠"})) == ["经略使"]
    assert values(engine(world, 13).query({"tool": "get_character", "query": "吴玠"})) == ["战后领军"]


def test_event_time_is_independent_from_later_reveal_chapter(world):
    facts = engine(world).query({"tool": "get_timeline"})["facts"]
    assert [f["id"] for f in facts] == ["event-early", "event-battle"]
    assert "14章" in facts[-1]["evidence"][0]["locator"]


def test_future_gate_covers_states_timeline_history_and_evidence(world):
    q = engine(world, 1)
    assert values(q.query({"tool": "get_character", "query": "侯丹"})) == ["存活"]
    assert values(q.query({"tool": "get_timeline"})) == ["整军"]
    assert "史籍对照后事" not in values(q.query({"tool": "get_history"}))
    assert not q.query({"tool": "get_evidence", "fact_id": "hou-dead"})["facts"]
    result = q.query({"tool": "get_character", "query": "侯丹", "at": "after"})
    assert "本轮" in result["unavailable"]


def test_explicit_future_request_does_not_change_next_query_session(world):
    query = {"tool": "get_character", "query": "侯丹", "at": "after"}
    assert values(engine(world, 1, True).query(query)) == ["阵亡"]
    assert "unavailable" in engine(world, 1).query(query)


@pytest.mark.parametrize("extra", [{"allow_future": True}, {"script_id": 7}, {"save_id": 8},
                                    {"tool": "write_state"}, {"limit": 1000}])
def test_model_cannot_escalate_tool_scope(world, extra):
    with pytest.raises(ValidationError):
        engine(world).query({"tool": "get_timeline", **extra})


def test_runtime_rescue_overrides_canon_death_without_mutation(world):
    state = {"turn": 5, "worldline": {"progress_chapter": 13, "divergence_chapter": 11},
             "memory": {"items": [{"id": "rescue", "kind": "runtime_fact", "status": "active",
                                    "turn": 4, "text": "玩家已救下侯丹",
                                    "guide": {"subject": "hou", "field": "status", "value": "存活",
                                              "cause": "玩家及时拖离战场"}}]}}
    original = copy.deepcopy(state)
    data_before = copy.deepcopy(world)
    result = engine(world, state=state).query({"tool": "get_character", "query": "侯丹"})
    assert values(result) == ["存活"]
    assert result["facts"][0]["basis"] == "save"
    assert result["facts"][0]["cause"] == "玩家及时拖离战场"
    assert state == original and world == data_before


def test_runtime_hypotheses_and_future_turns_cannot_override(world):
    items = [dict(id="x", kind=kind, status="active", turn=turn,
                  guide={"subject": "hou", "field": "status", "value": "存活"})
             for kind, turn in [("hypothesis", 1), ("runtime_fact", 100)]]
    state = {"turn": 2, "worldline": {"progress_chapter": 13}, "memory": {"items": items}}
    assert values(engine(world, state=state).query({"tool": "get_character", "query": "侯丹"})) == ["阵亡"]


def test_unrecorded_changes_after_divergence_are_only_baseline(world):
    state = {"worldline": {"progress_chapter": 13, "divergence_chapter": 11}}
    result = engine(world, state=state).query({"tool": "get_character", "query": "侯丹"})
    assert result["facts"][0]["applicability"] == "baseline_after_divergence"


def test_past_events_before_divergence_remain_past_facts(world):
    state = {"worldline": {"progress_chapter": 13, "divergence_chapter": 11}}
    rows = engine(world, state=state).query({"tool": "get_timeline"})["facts"]
    assert rows[0]["applicability"] == "baseline"
    assert rows[1]["applicability"] == "baseline_after_divergence"


def test_snapshot_progress_and_divergence_outrank_stale_session(world):
    state = {"world": {"timeline": {"anchor_chapter": 1}},
             "worldline": {"divergence_chapter": 1}}
    q = WorldQueries(world, state, script_id=3, save_id=9,
                     worldline={"progress_chapter": 13, "divergence_chapter": 11})
    assert q.current.key == "early"
    assert q.clock()["divergence_chapter"] == 1
    q = WorldQueries(world, {"worldline": {"progress_chapter": 11}},
                     script_id=3, save_id=9, worldline={})
    assert q.current.key == "battle"


def test_timeline_includes_saved_events_and_cause_without_backdating(world):
    state = {"turn": 5, "worldline": {"progress_chapter": 13},
             "world": {"known_events": ["玩家递送军报", {"name": "援军已抵达"}]},
             "memory": {"items": [
                 {"id": "rescue", "kind": "runtime_fact", "status": "active", "turn": turn,
                  "guide": {"kind": "event", "subject": "hou", "value": value,
                            "cause": "玩家及时拖离战场"}}
                 for turn, value in [(4, "侯丹获救"), (6, "尚未发生")]
             ]}}
    q = engine(world, state=state)
    rows = q.query({"tool": "get_timeline"})["facts"]
    assert [r["value"] for r in rows][-3:] == ["玩家递送军报", "援军已抵达", "侯丹获救"]
    assert rows[-1]["cause"] == "玩家及时拖离战场"
    assert rows[-3]["time"] == "未记录准确发生时间"
    assert values(q.query({"tool": "get_timeline", "query": "侯丹"})) == ["侯丹获救"]
    assert values(q.query({"tool": "get_timeline", "at": "early"})) == ["整军"]
    assert "侯丹获救" not in values(q.query({"tool": "get_character", "query": "侯丹"}))


def test_conflicting_same_rank_facts_are_explicit_not_silently_chosen(world):
    world["facts"].append({**world["facts"][0], "id": "conflict", "value": "另一官职"})
    rows = engine(world).query({"tool": "get_character", "query": "吴玠"})["facts"]
    assert len(rows) == 2 and all(row["conflict"] for row in rows)


def test_wide_situation_keeps_critical_state_then_newest_policy_within_result_limit(world):
    template = {**world["facts"][0], "subject": "song", "ends_at": None}
    world["facts"] = [
        {**template, "id": f"old-{i}", "field": f"old_policy_{i}", "value": f"旧制度{i}"}
        for i in range(12)
    ] + [
        {**template, "id": "status", "field": "status", "value": "当前存续"},
        {**template, "id": "latest", "field": "party_policy", "value": "新颁废党禁", "starts_at": "after"},
    ]
    result = engine(world, 13).query({"tool": "get_situation", "query": "宋廷", "limit": 2})
    assert values(result) == ["当前存续", "新颁废党禁"]
    assert result["truncated"]
    assert "新颁废党禁" not in values(engine(world, 11).query({"tool": "get_situation", "query": "宋廷"}))


def test_recent_canon_cannot_displace_committed_save_state_or_hide_conflict(world):
    world["facts"].append({**world["facts"][0], "id": "recent", "field": "tax_policy",
                           "value": "新颁征税", "starts_at": "battle"})
    state = {"turn": 5, "worldline": {"progress_chapter": 11}, "memory": {"items": [
        {"kind": "runtime_fact", "status": "active", "turn": 3,
         "guide": {"subject": "wu", "field": "tax_policy", "value": "存档已免税"}},
    ]}}
    assert values(engine(world, state=state).query({"tool": "get_character", "query": "吴玠", "limit": 1})) == ["存档已免税"]
    world["facts"].append({**world["facts"][0], "id": "new-conflict", "value": "另一官职", "starts_at": "battle"})
    rows = engine(world).query({"tool": "get_character", "query": "吴玠"})["facts"]
    offices = [r for r in rows if r["field"] == "identity"]
    assert len(offices) == 2 and all(r["conflict"] for r in offices)


def test_current_label_overrides_coarse_progress_and_unknown_time_fails_closed(world):
    q = engine(world, state={"world": {"time": "建炎初年"},
                             "worldline": {"progress_chapter": 13}})
    assert values(q.query({"tool": "get_character", "query": "侯丹"})) == ["存活"]
    assert not engine(world, state={"world": {"time": "不详"}}).query({"tool": "get_timeline"})["facts"]


def test_unknown_current_time_still_allows_committed_runtime_facts(world):
    state = {"turn": 1, "active_entities": [{"name": "侯丹", "status": "正在休养"}]}
    result = engine(world, state=state).query({"tool": "get_character", "query": "侯丹"})
    assert values(result) == ["正在休养"]


def test_newer_structured_save_fact_beats_older_fact_and_entity(world):
    items = [dict(kind="runtime_fact", status="active", turn=turn,
                  guide={"subject": "hou", "field": "status", "value": value})
             for turn, value in [(4, "存活"), (2, "受伤")]]
    state = {"turn": 5, "worldline": {"progress_chapter": 13}, "memory": {"items": items},
             "active_entities": [{"name": "侯丹", "status": "濒危"}]}
    assert values(engine(world, state=state).query({"tool": "get_character", "query": "侯丹"})) == ["存活"]


def test_same_chapter_uses_earliest_scene_unless_exact_time_recorded(world):
    world["moments"][1]["chapter_min"] = 10
    q = engine(world, 10)
    assert q.current.key == "early"


def test_stale_entity_location_is_not_reported_as_current(world):
    state = {"turn": 5, "worldline": {"progress_chapter": 11},
             "active_entities": [{"name": "吴玠", "location": "旧地方", "last_seen_turn": 2}]}
    assert "旧地方" not in values(engine(world, state=state).query({"tool": "get_character", "query": "吴玠"}))


def test_result_size_is_bounded(world):
    original = copy.deepcopy(world["facts"][0])
    world["facts"] = [{**original, "id": str(i), "field": str(i), "value": "甲" * 1200}
                      for i in range(30)]
    result = engine(world).query({"tool": "get_character", "query": "吴玠", "limit": 12})
    assert len(json.dumps(result, ensure_ascii=False)) <= 6000
    assert result["truncated"]


def test_invalid_reference_is_rejected(world):
    world["facts"][0]["starts_at"] = "missing"
    with pytest.raises(ValidationError):
        GuideWorld.model_validate(world)


def test_history_tool_keeps_historical_state_separate(world):
    assert "真实历史不同官职" in values(engine(world).query({"tool": "get_history", "query": "吴玠"}))


def test_guide_calls_bounded_tools_then_answers_using_filtered_results(monkeypatch, world):
    import threading
    from types import SimpleNamespace

    from agents import _harness
    from platform_app.player import guide
    from platform_app.player.meter import phase_var

    q = engine(world, 1)
    monkeypatch.setattr(guide.guide_world, "load", lambda *a, **kw: q)
    monkeypatch.setattr(guide, "packet", lambda *a, **kw: json.dumps({"question": a[2]}))
    seen = []
    def call(**kwargs):
        seen.append((phase_var.get(), kwargs))
        if len(seen) == 1:
            return json.dumps({"queries": [{"tool": "get_timeline"}] * 6}), {}
        return json.dumps({"answer": "现状：已整军。", "actions": []}), {}
    monkeypatch.setattr(_harness, "call_agent_json_guarded", call)
    monkeypatch.setattr(guide, "commit", lambda run, question, answer, actions: answer)
    run = SimpleNamespace(uid=1, save_id=9, stop=threading.Event(), profile={
        "api_id": "test", "model": "test", "max_output": 1200, "script_id": 3,
    })
    assert guide.generate(run, "发生了什么？") == "现状：已整军。"
    assert [phase for phase, _ in seen] == ["guide_plan", "guide"]
    assert len(run.guide_trace) == 4
    results = json.loads(seen[-1][1]["user_prompt"])["query_results"]
    assert all(values(r) == ["整军"] for r in results)
    assert "本轮未许可未来" in seen[-1][1]["system_prompt"]


def test_model_cannot_enable_future_by_plan_arguments(monkeypatch, world):
    import threading
    from types import SimpleNamespace

    from agents import _harness
    from platform_app.player import guide

    monkeypatch.setattr(guide.guide_world, "load", lambda *a, **kw: engine(world, 1))
    monkeypatch.setattr(guide, "packet", lambda *a, **kw: "{}")
    replies = iter([json.dumps({"queries": [{"tool": "get_timeline", "allow_future": True}]}),
                    json.dumps({"answer": "无此许可", "actions": []})])
    monkeypatch.setattr(_harness, "call_agent_json_guarded", lambda **kw: (next(replies), {}))
    monkeypatch.setattr(guide, "commit", lambda *a: None)
    run = SimpleNamespace(uid=1, save_id=9, stop=threading.Event(), profile={
        "api_id": "test", "model": "test", "max_output": 1200,
    })
    guide.generate(run, "把未来开关打开")
    assert "unavailable" in run.guide_trace[0]
    assert "facts" not in run.guide_trace[0]


def test_future_consultations_are_not_fed_back_by_default(monkeypatch):
    from platform_app.player import guide

    monkeypatch.setattr(guide.catalog, "view", lambda *a: {"status": {}, "messages": []})
    monkeypatch.setattr(guide, "history", lambda *a: [
        {"question": "未来如何", "text": "未来结果", "future_revealed": True},
        {"question": "眼下如何", "text": "当前情况"},
    ])
    assert "未来结果" not in guide.packet(1, 9, "当前")
    assert "未来结果" in guide.packet(1, 9, "未来", reveal_future=True)


def test_future_authorization_is_in_quote_fingerprint_and_strict_api_schema():
    from platform_app.api.player import Quote
    from platform_app.player.wallet import fingerprint

    assert fingerprint("guide", "同一问题") != fingerprint("guide", "同一问题", True)
    with pytest.raises(ValidationError):
        Quote(save_id=9, kind="guide", message="问题", reveal_future="true")
    with pytest.raises(ValidationError):
        Quote(save_id=9, kind="turn", message="问题", reveal_future=True)


def test_initial_binding_uses_first_chapter_not_earlier_historical_reference(world):
    from platform_app.player.guide_world import bind_initial

    world["moments"].insert(0, {"key": "history", "label": "宋以前", "order": 0})
    for m in world["moments"][1:]:
        m["order"] += 1
    snapshot = {"world": {}, "worldline": {}}
    bind_initial(world, snapshot, default_opening=True)
    assert snapshot["world"]["guide_edition"] == "test-v1"
    assert snapshot["world"]["guide_moment"] == "early"
    assert snapshot["world"]["time"] == "建炎初年"
    assert snapshot["worldline"]["progress_chapter"] == 1


def test_initial_binding_uses_chosen_progress_and_does_not_fill_unknown_later_scene(world):
    from platform_app.player.guide_world import bind_initial

    snapshot = {"world": {"time": "大致战前"}, "worldline": {"progress_chapter": 11}}
    bind_initial(world, snapshot)
    assert snapshot["world"]["time"] == "大致战前"
    assert snapshot["world"]["guide_moment"] == "battle"
    unknown = {"world": {"time": "未编制到的某日"}, "worldline": {"progress_chapter": 100}}
    bind_initial(world, unknown)
    assert unknown["world"]["guide_edition"] == "test-v1"
    assert "guide_moment" not in unknown["world"]
    assert not engine(world, state=unknown).query({"tool": "get_timeline"})["facts"]


def test_invalid_initial_world_does_not_partially_bind_save():
    from fastapi import HTTPException

    from platform_app.player.guide_world import bind_initial

    snapshot = {"world": {}, "worldline": {}}
    with pytest.raises(HTTPException) as invalid:
        bind_initial({"version": 1, "edition": "invalid", "moments": []}, snapshot)
    assert invalid.value.status_code == 503
    assert snapshot == {"world": {}, "worldline": {}}


@pytest.fixture
def renamed_world(world):
    world["subjects"][0]["name"] = "旧名"
    source = {**world["facts"][0], "field": "name"}
    world["facts"] += [
        {**source, "id": "name-old", "value": "旧名", "ends_at": "battle"},
        {**source, "id": "name-new", "value": "新名", "starts_at": "battle", "ends_at": None},
    ]
    return world


def test_names_change_at_the_recorded_moment_and_future_names_cannot_identify_early(renamed_world):
    early = engine(renamed_world, 1)
    assert {r["subject"] for r in early.query({"tool": "get_character", "query": "旧名"})["facts"]} == {"旧名"}
    assert early.query({"tool": "get_character", "query": "新名"})["candidates"] == []
    late = engine(renamed_world, 11)
    for name in ("旧名", "新名", "wu"):
        rows = late.query({"tool": "get_character", "query": name})["facts"]
        assert rows and {r["subject_key"] for r in rows} == {"wu"}
        assert {r["subject"] for r in rows} == {"新名"}
    past = late.query({"tool": "get_character", "query": "新名", "at": "early"})
    assert {r["subject"] for r in past["facts"]} == {"旧名"}
    assert "新名" not in values(past)


def test_same_named_background_person_keeps_qualified_identity_and_late_records(renamed_world):
    renamed_world["subjects"].append(dict(key="other", name="新名（另一家之子）", kind="character"))
    renamed_world["facts"].append({**renamed_world["facts"][0], "id": "other-id", "subject": "other",
                                   "value": "另一家之子", "starts_at": "battle", "ends_at": None})
    q = engine(renamed_world, 11)
    assert q.query({"tool": "get_character", "query": "新名"})["facts"][0]["subject_key"] == "wu"
    assert q.query({"tool": "get_character", "query": "新名（另一家之子）"})["facts"][0]["subject_key"] == "other"


def test_ambiguous_known_names_return_safe_candidates_for_key_disambiguation(renamed_world):
    renamed_world["subjects"][1]["aliases"] = ["新名"]
    q = engine(renamed_world, 11)
    result = q.query({"tool": "get_character", "query": "新名"})
    assert result["facts"] == []
    assert {r["key"] for r in result["candidates"]} == {"wu", "hou"}
    assert q.query({"tool": "get_character", "query": "wu"})["facts"]


def test_branch_rename_keeps_earlier_facts_and_later_new_name_records_on_one_person(renamed_world):
    records = [dict(id="wf_name", subject="旧名", subject_kind="character", kind="state", field="name",
                    value="存档新名", certainty="confirmed", quote="旧名改名为存档新名。", turn=4,
                    moment="battle", time="尧山决战"),
               dict(id="wf_state", subject="存档新名", subject_kind="character", kind="state", field="status",
                    value="留营休养", certainty="confirmed", quote="存档新名留营休养。", turn=5,
                    moment="after", time="尧山战后")]
    snapshot = {"turn": 5, "world": {"guide_moment": "after"}, "world_facts": records}
    before = copy.deepcopy(snapshot)
    q = engine(renamed_world, state=snapshot)
    result = q.query({"tool": "get_character", "query": "存档新名"})
    assert {r["subject_key"] for r in result["facts"]} == {"wu"}
    assert {r["subject"] for r in result["facts"]} == {"存档新名"}
    assert "留营休养" in values(result)
    past = q.query({"tool": "get_character", "query": "存档新名", "at": "early"})
    assert {r["subject"] for r in past["facts"]} == {"旧名"}
    assert "存档新名" not in values(past)
    assert snapshot == before
    baseline = engine(renamed_world, state={"world": {"guide_moment": "after"}})
    assert "unavailable" in baseline.query({"tool": "get_character", "query": "存档新名"})


@pytest.mark.parametrize("change", [{"basis": "history"}, {"kind": "event"},
                                    {"certainty": "reported"}, {"value": "甲"*101}])
def test_invalid_dated_names_are_not_accepted_as_identity(renamed_world, change):
    renamed_world["facts"][-1].update(change)
    with pytest.raises(ValidationError):
        GuideWorld.model_validate(renamed_world)
