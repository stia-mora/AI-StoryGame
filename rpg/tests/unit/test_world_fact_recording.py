import copy
import json

import pytest

from platform_app.player.guide_world import WorldQueries
from state import GameState
from state.world_facts import context

NARRATIVE = "你将侯丹拖离战阵。军医止血后确认侯丹尚活，右臂受伤，留营休养。"
RESCUE = dict(op="world_fact", subject="侯丹", subject_kind="character", field="status",
              value="存活，右臂受伤，留营休养", kind="state", certainty="confirmed",
              quote="军医止血后确认侯丹尚活，右臂受伤，留营休养。",
              cause="玩家拖离战阵并请军医止血", diverges=True)


def response(*ops, narrative=NARRATIVE):
    return narrative + "\n```json\n" + json.dumps(list(ops), ensure_ascii=False) + "\n```"


def state(mode="full_access"):
    g = GameState.new()
    g.data["turn"] = 5
    g.data["permissions"]["mode"] = mode
    g.data["world"].update(guide_edition="test", guide_moment="battle", time="尧山决战")
    g.data["worldline"]["progress_chapter"] = 12
    return g


@pytest.fixture
def model():
    return dict(version=1, edition="test", moments=[
        dict(key="before", order=0, label="战前", chapter_min=1, chapter_max=11),
        dict(key="battle", order=10, label="尧山决战", chapter_min=12, chapter_max=12),
        dict(key="after", order=20, label="战后", chapter_min=13, chapter_max=20),
    ], subjects=[dict(key="hou", name="侯丹", kind="character", aliases=["侯都头"])], facts=[
        dict(id="death", subject="hou", kind="state", field="status", value="原著阵亡",
             starts_at="battle", basis="novel", evidence=[dict(source="测试稿", locator="第12章")]),
    ])


def query(g, model, tool="get_character", **kwargs):
    return WorldQueries(model, g.data, script_id=1, save_id=2).query(
        dict(tool=tool, **({"query": "侯丹"} if tool == "get_character" else {}), **kwargs))


def test_narrated_rescue_survives_save_reload_and_memory_pruning(tmp_path, model):
    g = state()
    updates = g.apply_structured_updates(response(RESCUE))
    assert any("状态写入：世界事实" in u for u in updates)
    assert g.data["worldline"]["divergence_chapter"] == 12
    assert g.data["worldline"]["divergence_turn"] == 5
    g.data["memory"]["items"] = []
    path = tmp_path / "branch.json"
    g.save(path)
    restored = GameState(json.loads(path.read_text(encoding="utf-8")))
    rows = query(restored, model)["facts"]
    assert [r["value"] for r in rows] == [RESCUE["value"]]
    assert rows[0]["evidence"][0]["quote"] == RESCUE["quote"]
    assert "原著阵亡" not in context(restored.data)
    assert RESCUE["value"] in context(restored.data)


@pytest.mark.parametrize("mode", ["read_only", "default"])
def test_permission_pending_not_queried_until_approved_at_original_turn(mode, model):
    g = state(mode)
    updates = g.apply_structured_updates(response(RESCUE))
    assert any("待审" in u for u in updates)
    assert "world_facts" not in g.data
    assert query(g, model)["facts"][0]["value"] == "原著阵亡"
    pending = g.data["permissions"]["pending_writes"][0]
    g.data["turn"] = 8
    g.data["world"].update(guide_moment="after", time="战后")
    g.approve_pending_write(id=pending["id"])
    record = g.data["world_facts"][0]
    assert (record["turn"], record["moment"], record["time"]) == (5, "battle", "尧山决战")
    assert query(g, model)["facts"][0]["value"] == RESCUE["value"]
    assert not query(g, model, at="before")["facts"]
    assert query(g, model, at="battle")["facts"][0]["value"] == RESCUE["value"]


def test_rejected_and_json_only_claims_never_become_facts(model):
    g = state("read_only")
    g.apply_structured_updates(response(RESCUE))
    g.reject_pending_write(id=g.data["permissions"]["pending_writes"][0]["id"])
    assert "world_facts" not in g.data
    g = state()
    g.apply_structured_updates(response(RESCUE, narrative="你打算救人，尚未动手。"))
    assert "world_facts" not in g.data
    g.apply_structured_updates(response({**RESCUE, "quote": "右臂受伤"}))
    assert "world_facts" not in g.data  # Quote must identify the subject.


@pytest.mark.parametrize("extra", [{"turn": 999}, {"save_id": 3}, {"certainty": "inferred"},
                                    {"kind": "event"}, {"certainty": "reported"}])
def test_untrusted_ops_cannot_set_provenance_or_change_semantics(extra):
    g = state()
    g.apply_structured_updates(response({**RESCUE, **extra}))
    assert "world_facts" not in g.data


def test_generic_state_paths_cannot_bypass_narration_proof():
    g = state()
    for path in ("world_facts", "world_facts.0", "world_facts.fake"):
        assert "拒绝" in g.apply_state_write_typed(path, [RESCUE], force=True)
    assert "world_facts" not in g.data


def test_duplicate_and_per_turn_limit_and_latest_state(model):
    g = state()
    g.apply_structured_updates(response(RESCUE, RESCUE))
    assert len(g.data["world_facts"]) == 1
    for i in range(20):
        g.apply_structured_updates(response({**RESCUE, "field": f"detail_{i}", "value": f"记录{i}"}))
    assert len(g.data["world_facts"]) == 12
    g.data["turn"] = 6
    g.apply_structured_updates(response({**RESCUE, "value": "伤势稳定", "diverges": False}))
    assert query(g, model)["facts"][0]["value"] == "伤势稳定"
    assert "伤势稳定" in context(g.data) and RESCUE["value"] not in context(g.data)


def test_reports_and_proposals_do_not_replace_death_or_mark_divergence(model):
    g = state()
    g.apply_structured_updates(response({**RESCUE, "field": "report", "certainty": "reported",
                                         "value": "有军士称侯丹获救", "diverges": False},
                                        {**RESCUE, "field": "proposal", "value": "拟加军职", "diverges": False}))
    rows = query(g, model)["facts"]
    assert any(r["value"] == "原著阵亡" for r in rows)
    assert any(r["certainty"] == "reported" for r in rows)
    assert "divergence_turn" not in g.data["worldline"]
    assert not query(g, model, "get_timeline")["facts"]


def test_event_and_evidence_queries_include_new_save_only_subject(model):
    g = state()
    prose = "军医周十一止住了流血，营中转运已恢复。"
    event = {**RESCUE, "subject": "周十一", "kind": "event", "field": "event",
             "value": "止血救人", "quote": prose, "diverges": False}
    g.apply_structured_updates(response(event, narrative=prose))
    timeline = query(g, model, "get_timeline")
    assert timeline["facts"][0]["value"] == "止血救人"
    rid = timeline["facts"][0]["id"]
    assert query(g, model, "get_evidence", fact_id=rid)["facts"][0]["evidence"][0]["quote"] == prose
    original = copy.deepcopy(g.data)
    assert not query(g, model, "get_timeline", at="before")["facts"]
    assert g.data == original


def test_recording_requires_enabled_edition():
    g = state()
    del g.data["world"]["guide_edition"]
    g.apply_structured_updates(response(RESCUE))
    assert "world_facts" not in g.data


def test_time_updates_invalidate_old_exact_moment_before_recording():
    g = state()
    time_op = dict(op="set", path="world.time", value="战后")
    g.apply_structured_updates(response(RESCUE, time_op))
    row = g.data["world_facts"][0]
    assert row["time"] == "战后"
    assert row["moment"] == ""


def test_director_bundle_includes_world_facts_after_memory_pruning(model):
    from context_engine import build_context_bundle
    from context_providers import resolve_content_pack

    g = state()
    g.apply_structured_updates(response(RESCUE))
    g.data["memory"]["items"] = []
    result = build_context_bundle(g, user_input="问侯丹伤势", contributions=[],
                                  manifest=resolve_content_pack(g))
    assert RESCUE["value"] in result["prompt"]
    assert "不自动成为角色本人所知" in result["prompt"]


def test_recorder_native_schema_and_prompt_agree_on_world_fact(monkeypatch):
    from agents import recorder

    monkeypatch.setattr(recorder, "_resolve_recorder_api_and_model", lambda *a: ("test", "test"))
    captured = []
    def call(**kwargs):
        captured.append(kwargs)
        return json.dumps({"ops": [RESCUE]}), {}
    monkeypatch.setattr(recorder, "_call_recorder", call)
    result = recorder.record_turn(NARRATIVE, state().data, tasks=["ops"])
    assert result["ops"] == [RESCUE]
    assert "世界事实记录" in captured[0]["system_prompt"]
    properties = captured[0]["tool_schema"]["input_schema"]["properties"]["ops"]["items"]["properties"]
    assert "world_fact" in properties["op"]["enum"]
    assert {"subject", "subject_kind", "quote", "cause", "diverges"} <= properties.keys()
    assert "type" not in properties["value"]  # Normal array-valued ops still work.
    recorder.record_turn(NARRATIVE, {}, tasks=["ops"])
    assert "世界事实记录" not in captured[1]["system_prompt"]
    assert "world_fact" not in captured[1]["tool_schema"]["input_schema"]["properties"]["ops"]["items"]["properties"]["op"]["enum"]


def test_legacy_extractor_enables_world_fact_instructions(monkeypatch):
    from agents import extractor

    seen = []
    def call(**kwargs):
        seen.append(kwargs)
        return json.dumps([RESCUE]), None
    monkeypatch.setattr(extractor, "_call_extractor_backend", call)
    result = extractor.extract_state_ops(NARRATIVE, state().data, api_id_override="test", model_override="test")
    assert result == [RESCUE]
    assert "世界事实记录" in seen[0]["system_prompt"]


def test_legacy_extractor_native_schema_supports_world_fact_without_restricting_other_values(monkeypatch):
    from types import SimpleNamespace

    from agents import _harness, extractor
    from platform_app import user_credentials
    from state.world_facts import RECORDING_GUIDE

    seen = []
    def create(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(content=[], usage=None)
    monkeypatch.setattr(user_credentials, "resolve_api_key", lambda *a, **kw: {"key": "test"})
    monkeypatch.setattr(_harness, "micro_task_anthropic_client", lambda *a, **kw: SimpleNamespace(
        messages=SimpleNamespace(create=create)))
    extractor._call_anthropic_tool_use("test", RECORDING_GUIDE, "正文", None)
    properties = seen[0]["tools"][0]["input_schema"]["properties"]["ops"]["items"]["properties"]
    assert "world_fact" in properties["op"]["enum"]
    assert "quote" in properties and "type" not in properties["value"]
